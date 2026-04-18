from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from typing import Any

from .failure_analyzer import analyze_failure
from .git_tools import ensure_git_repository, get_git_status
from .grader import choose_best_attempt
from .interpreter import interpret_request
from .memory_manager import build_target_dir_hint, select_output_dir, summarize_memory, update_project_memory
from .models import AgentJob
from .parallel_upgrader import (
    build_parallel_upgrade_candidates,
    choose_best_parallel_candidate,
    prepare_upgrade_directory,
    select_recommended_upgrade,
)
from .planner import build_execution_plan
from .queue_store import append_job, read_active_project, read_project_memory, upsert_job, write_state
from .workers import BrowserWorker, CodingWorker, ResearchWorker, ReviewWorker, RunWorker, TestWorker


WORKERS = [
    BrowserWorker(),
    ResearchWorker(),
    CodingWorker(),
    RunWorker(),
    TestWorker(),
    ReviewWorker(),
]

CONTINUATION_KEYWORDS = ("계속", "이어", "다음", "고도화", "개선", "수정", "보완", "업그레이드", "리팩토링")


def parse_jsonish(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def dispatch(job: AgentJob) -> AgentJob:
    for worker in WORKERS:
        if worker.can_handle(job):
            processed = worker.process(job)
            processed.updated_at = time.time()
            return processed
    job.status = "error"
    job.summary = f"처리 가능한 워커를 찾지 못했습니다: {job.category}"
    job.result = {"error": job.summary}
    job.updated_at = time.time()
    return job


def make_project_id(prompt: str) -> str:
    normalized = re.sub(r"\s+", " ", prompt.strip().lower())
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", normalized).strip("-")[:40] or "project"
    return f"{slug}-{digest}"


def resolve_project_id(prompt: str, interpretation: dict[str, Any]) -> str:
    active = read_active_project()
    continuation = bool(interpretation.get("continuation")) or any(keyword in prompt for keyword in CONTINUATION_KEYWORDS)
    if continuation and active:
        active_id = str(active.get("project_id") or "").strip()
        if active_id:
            return active_id
    return make_project_id(interpretation.get("project_title") or prompt)


def register_job(prompt: str, interpretation: dict[str, Any], project_id: str) -> AgentJob:
    job = AgentJob(
        prompt=prompt.strip(),
        category=str(interpretation.get("route_category") or "coding"),
        project_id=project_id,
        domain_mode=str(interpretation.get("domain_mode") or "general_mode"),
        goal=str(interpretation.get("goal_summary") or prompt.strip()),
        stage="queued",
        metadata={"interpretation": interpretation},
    )
    append_job(job)
    return job


def run_stage(
    *,
    prompt: str,
    category: str,
    project_id: str,
    domain_mode: str,
    goal: str,
    metadata: dict[str, Any],
    pipeline: list[dict[str, Any]],
) -> AgentJob:
    job = AgentJob(
        prompt=prompt,
        category=category,
        project_id=project_id,
        domain_mode=domain_mode,
        goal=goal,
        stage=category,
        metadata=metadata,
    )
    processed = dispatch(job)
    upsert_job(processed)
    pipeline.append(
        {
            "worker": processed.assigned_worker,
            "category": category,
            "status": processed.status,
            "summary": processed.summary,
        }
    )
    return processed


def build_retry_prompt(
    prompt: str,
    failure_analysis: dict[str, Any],
    implementation: dict[str, Any],
    run_result: dict[str, Any],
    test_result: dict[str, Any],
    review: dict[str, Any],
) -> str:
    lines = [
        prompt,
        "",
        "이전 시도에서 실패가 발생했습니다. 아래 정보를 반영해 다시 수정하세요.",
        f"- 실패 유형: {', '.join(failure_analysis.get('failure_types') or []) or 'unknown'}",
    ]
    hypotheses = failure_analysis.get("hypotheses") or []
    if hypotheses:
        lines.append("- 원인 가설")
        lines.extend(f"  - {item}" for item in hypotheses[:4])
    fixes = failure_analysis.get("recommended_fixes") or []
    if fixes:
        lines.append("- 권장 수정 지시")
        lines.extend(f"  - {item}" for item in fixes[:6])
    if run_result.get("error"):
        lines.append(f"- 실행 오류: {run_result['error']}")
    for failure in (test_result.get("failures") or implementation.get("validation", {}).get("failures") or [])[:5]:
        lines.append(f"- 검증 실패: {failure}")
    review_issues = review.get("issues") or []
    for issue in review_issues[:4]:
        lines.append(f"- 리뷰 이슈: {issue}")
    return "\n".join(lines)


def finalize_state(
    root_job: AgentJob,
    interpretation: dict[str, Any],
    plan: dict[str, Any],
    pipeline: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    grade: dict[str, Any],
    project_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    best_attempt = grade.get("best_attempt") or {}
    review = best_attempt.get("review") or {}
    final_status = "done" if grade.get("status") in {"good", "needs_work"} else "error"
    summary = review.get("summary") or best_attempt.get("summary") or root_job.summary
    result = {
        "interpretation": interpretation,
        "plan": plan,
        "attempts": attempts,
        "grade": {key: value for key, value in grade.items() if key != "best_attempt"},
        "best_attempt": best_attempt,
        "project_memory": project_memory or {},
        "pipeline": pipeline,
    }
    state = {
        "status": final_status,
        "jobId": root_job.id,
        "projectId": root_job.project_id,
        "prompt": root_job.prompt,
        "category": root_job.category,
        "domainMode": root_job.domain_mode,
        "assignedWorker": "orchestrator",
        "summary": summary,
        "result": result,
        "pipeline": pipeline,
        "updated_at": time.time(),
    }
    write_state(state)
    root_job.status = final_status
    root_job.stage = "completed"
    root_job.summary = summary
    root_job.result = result
    root_job.metadata.update({"interpretation": interpretation, "plan": plan})
    upsert_job(root_job)
    return state


def choose_browser_prompt(root_prompt: str, interpretation: dict[str, Any], attempt_index: int, failure_analysis: dict[str, Any]) -> str:
    if interpretation.get("requires_browser"):
        return root_prompt
    if attempt_index > 0 and failure_analysis.get("search_queries"):
        queries = failure_analysis.get("search_queries") or []
        return str(queries[0]) if queries else ""
    queries = interpretation.get("search_queries") or []
    return str(queries[0]) if queries else ""


def run_upgrade_candidate(
    *,
    root_job: AgentJob,
    interpretation: dict[str, Any],
    plan: dict[str, Any],
    base_attempt: dict[str, Any],
    candidate: dict[str, Any],
    pipeline: list[dict[str, Any]],
    candidate_index: int,
) -> dict[str, Any]:
    base_implementation = base_attempt.get("implementation") or {}
    base_output_dir = str(base_implementation.get("output_dir") or "").strip()
    if not base_output_dir:
        return {}

    target_dir = prepare_upgrade_directory(base_output_dir, str(candidate.get("name") or f"candidate_{candidate_index}"))
    upgrade_prompt = "\n\n".join(
        [
            root_job.prompt,
            build_target_dir_hint(target_dir),
            f"UPGRADE_CANDIDATE: {candidate.get('name', '')}",
            f"UPGRADE_GOAL: {candidate.get('goal', '')}",
            f"UPGRADE_INSTRUCTION: {candidate.get('prompt_addition', '')}",
        ]
    )

    built = run_stage(
        prompt=upgrade_prompt,
        category="coding",
        project_id=root_job.project_id,
        domain_mode=root_job.domain_mode,
        goal=root_job.goal,
        metadata={
            "interpretation": interpretation,
            "plan": plan,
            "research": base_attempt.get("research") or {},
            "browser_context": base_attempt.get("browser") or {},
            "target_output_dir": str(target_dir),
            "upgrade_candidate": candidate.get("name", ""),
        },
        pipeline=pipeline,
    )
    implementation = parse_jsonish(built.result)

    executed = run_stage(
        prompt=root_job.prompt,
        category="run",
        project_id=root_job.project_id,
        domain_mode=root_job.domain_mode,
        goal=root_job.goal,
        metadata={"implementation": implementation},
        pipeline=pipeline,
    )
    run_result = parse_jsonish(executed.result)

    tested = run_stage(
        prompt=root_job.prompt,
        category="test",
        project_id=root_job.project_id,
        domain_mode=root_job.domain_mode,
        goal=root_job.goal,
        metadata={"implementation": implementation},
        pipeline=pipeline,
    )
    test_result = parse_jsonish(tested.result)

    reviewed = run_stage(
        prompt=root_job.prompt,
        category="review",
        project_id=root_job.project_id,
        domain_mode=root_job.domain_mode,
        goal=root_job.goal,
        metadata={
            "review_payload": {
                "implementation": implementation,
                "run_result": run_result,
                "test_result": test_result,
                "research_report": base_attempt.get("research") or {},
                "browser_context": base_attempt.get("browser") or {},
                "interpretation": interpretation,
            }
        },
        pipeline=pipeline,
    )
    review_result = parse_jsonish(reviewed.result)

    return {
        "variant_label": f"upgrade:{candidate.get('name', '')}",
        "summary": reviewed.summary or built.summary,
        "candidate": candidate,
        "attempt": {
            "attempt_index": candidate_index,
            "variant_label": f"upgrade:{candidate.get('name', '')}",
            "research": base_attempt.get("research") or {},
            "browser": base_attempt.get("browser") or {},
            "implementation": implementation,
            "run": run_result,
            "test": test_result,
            "review": review_result,
            "summary": reviewed.summary or built.summary,
        },
    }


def run_parallel_upgrades(
    *,
    root_job: AgentJob,
    interpretation: dict[str, Any],
    plan: dict[str, Any],
    best_attempt: dict[str, Any],
    pipeline: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = build_parallel_upgrade_candidates(best_attempt, interpretation, plan)
    recommended = select_recommended_upgrade(candidates)
    executable_candidates = candidates[:3]
    executed: list[dict[str, Any]] = []

    for index, candidate in enumerate(executable_candidates):
        try:
            result = run_upgrade_candidate(
                root_job=root_job,
                interpretation=interpretation,
                plan=plan,
                base_attempt=best_attempt,
                candidate=candidate,
                pipeline=pipeline,
                candidate_index=index,
            )
            if result:
                candidate_attempt = result.get("attempt") or {}
                candidate_grade = choose_best_attempt([candidate_attempt])
                executed.append(
                    {
                        "name": candidate.get("name", ""),
                        "goal": candidate.get("goal", ""),
                        "attempt": candidate_attempt,
                        "grade": {
                            "score": candidate_grade.get("score", 0),
                            "status": candidate_grade.get("status", "blocked"),
                        },
                        "output_dir": ((candidate_attempt.get("implementation") or {}).get("output_dir") or ""),
                    }
                )
                pipeline.append(
                    {
                        "worker": "parallel_upgrader",
                        "category": "upgrade_candidate",
                        "status": "done",
                        "summary": f"{candidate.get('name', '')} score={candidate_grade.get('score', 0)}",
                    }
                )
        except Exception as exc:
            executed.append(
                {
                    "name": candidate.get("name", ""),
                    "goal": candidate.get("goal", ""),
                    "grade": {"score": 0, "status": "blocked"},
                    "error": str(exc),
                }
            )
            pipeline.append(
                {
                    "worker": "parallel_upgrader",
                    "category": "upgrade_candidate",
                    "status": "error",
                    "summary": f"{candidate.get('name', '')}: {exc}",
                }
            )

    best_candidate = choose_best_parallel_candidate(executed)
    return {
        "candidates": candidates,
        "recommended": recommended,
        "executed": executed,
        "best_executed": best_candidate,
    }


def run_coding_pipeline(root_job: AgentJob, interpretation: dict[str, Any], plan: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
    pipeline: list[dict[str, Any]] = []
    repo_status = ensure_git_repository()
    pipeline.append(
        {
            "worker": "git",
            "category": "repository",
            "status": "done" if repo_status.get("enabled") else "blocked",
            "summary": repo_status.get("branch") or repo_status.get("error") or repo_status.get("root", ""),
        }
    )
    output_dir = select_output_dir(root_job.project_id, memory, bool(interpretation.get("continuation")))
    memory_summary = summarize_memory(memory)
    max_attempts = max(1, int(plan.get("repair_budget", 1) or 1))
    attempts: list[dict[str, Any]] = []
    research_report: dict[str, Any] = {}
    browser_context: dict[str, Any] = {}
    current_prompt = root_job.prompt
    failure_analysis: dict[str, Any] = {}

    for attempt_index in range(max_attempts):
        browser_prompt = choose_browser_prompt(root_job.prompt, interpretation, attempt_index, failure_analysis)
        if browser_prompt:
            browsed = run_stage(
                prompt=browser_prompt,
                category="browser",
                project_id=root_job.project_id,
                domain_mode=root_job.domain_mode,
                goal=root_job.goal,
                metadata={"interpretation": interpretation, "plan": plan},
                pipeline=pipeline,
            )
            browser_context = parse_jsonish(browsed.result)

        research_prompt = current_prompt
        if attempt_index > 0 and failure_analysis.get("search_queries"):
            research_prompt = current_prompt + "\n\n참고 검색 질의:\n- " + "\n- ".join(failure_analysis.get("search_queries")[:5])

        researched = run_stage(
            prompt=research_prompt,
            category="research",
            project_id=root_job.project_id,
            domain_mode=root_job.domain_mode,
            goal=root_job.goal,
            metadata={
                "interpretation": interpretation,
                "plan": plan,
                "memory_summary": memory_summary,
                "browser_context": browser_context,
            },
            pipeline=pipeline,
        )
        research_report = parse_jsonish(researched.result) or {"summary": str(researched.result or "")}

        build_prompt_parts = [
            current_prompt,
            build_target_dir_hint(output_dir),
        ]
        if memory_summary:
            build_prompt_parts.append("기존 프로젝트 메모리\n" + memory_summary)
        if browser_context:
            build_prompt_parts.append("브라우저 결과:\n" + json.dumps(browser_context, ensure_ascii=False, indent=2))
        if research_report:
            build_prompt_parts.append("조사 결과:\n" + json.dumps(research_report, ensure_ascii=False, indent=2))
        if attempt_index > 0 and failure_analysis:
            build_prompt_parts.append("실패 분석:\n" + json.dumps(failure_analysis, ensure_ascii=False, indent=2))

        built = run_stage(
            prompt="\n\n".join(build_prompt_parts),
            category="coding",
            project_id=root_job.project_id,
            domain_mode=root_job.domain_mode,
            goal=root_job.goal,
            metadata={
                "interpretation": interpretation,
                "plan": plan,
                "research": research_report,
                "browser_context": browser_context,
                "target_output_dir": str(output_dir),
                "failure_analysis": failure_analysis,
            },
            pipeline=pipeline,
        )
        implementation = parse_jsonish(built.result)

        executed = run_stage(
            prompt=root_job.prompt,
            category="run",
            project_id=root_job.project_id,
            domain_mode=root_job.domain_mode,
            goal=root_job.goal,
            metadata={"implementation": implementation},
            pipeline=pipeline,
        )
        run_result = parse_jsonish(executed.result)

        tested = run_stage(
            prompt=root_job.prompt,
            category="test",
            project_id=root_job.project_id,
            domain_mode=root_job.domain_mode,
            goal=root_job.goal,
            metadata={"implementation": implementation},
            pipeline=pipeline,
        )
        test_result = parse_jsonish(tested.result)

        reviewed = run_stage(
            prompt=root_job.prompt,
            category="review",
            project_id=root_job.project_id,
            domain_mode=root_job.domain_mode,
            goal=root_job.goal,
            metadata={
                "review_payload": {
                    "implementation": implementation,
                    "run_result": run_result,
                    "test_result": test_result,
                    "research_report": research_report,
                    "browser_context": browser_context,
                    "interpretation": interpretation,
                }
            },
            pipeline=pipeline,
        )
        review_result = parse_jsonish(reviewed.result)

        attempt_record = {
            "attempt_index": attempt_index,
            "variant_label": "base",
            "summary": reviewed.summary or built.summary,
            "research": research_report,
            "browser": browser_context,
            "implementation": implementation,
            "run": run_result,
            "test": test_result,
            "review": review_result,
        }
        attempts.append(attempt_record)

        failure_analysis = analyze_failure(
            root_job.prompt,
            interpretation,
            implementation,
            run_result,
            test_result,
            review_result,
            attempt_index=attempt_index,
            max_attempts=max_attempts,
        )
        pipeline.append(
            {
                "worker": "failure_analyzer",
                "category": "failure_analysis",
                "status": "done",
                "summary": ", ".join(failure_analysis.get("failure_types") or ["no_failure"]),
            }
        )

        if not failure_analysis.get("should_retry"):
            break
        current_prompt = build_retry_prompt(root_job.prompt, failure_analysis, implementation, run_result, test_result, review_result)

    grade = choose_best_attempt(attempts)
    pipeline.append(
        {
            "worker": "grader",
            "category": "grading",
            "status": "done",
            "summary": f"base_best_attempt={grade.get('best_attempt_index')} score={grade.get('score')}",
        }
    )

    base_best_attempt = grade.get("best_attempt") or {}
    parallel_upgrades = {}
    selection_attempts = list(attempts)
    if interpretation.get("route_category") == "coding" and base_best_attempt:
        parallel_upgrades = run_parallel_upgrades(
            root_job=root_job,
            interpretation=interpretation,
            plan=plan,
            best_attempt=base_best_attempt,
            pipeline=pipeline,
        )
        for item in parallel_upgrades.get("executed") or []:
            candidate_attempt = item.get("attempt") or {}
            if candidate_attempt:
                selection_attempts.append(candidate_attempt)

    final_grade = choose_best_attempt(selection_attempts)
    final_best_candidate_name = str(((final_grade.get("best_attempt") or {}).get("implementation") or {}).get("upgrade_candidate") or "").strip()
    if final_best_candidate_name and parallel_upgrades.get("executed"):
        for item in parallel_upgrades.get("executed") or []:
            if str(item.get("name") or "").strip() == final_best_candidate_name:
                parallel_upgrades["best_executed"] = item
                break
    pipeline.append(
        {
            "worker": "grader",
            "category": "final_selection",
            "status": "done",
            "summary": f"final_best_attempt={final_grade.get('best_attempt_index')} score={final_grade.get('score')}",
        }
    )

    project_memory = update_project_memory(
        root_job.project_id,
        root_job.prompt,
        interpretation,
        plan,
        final_grade.get("best_attempt") or {},
        final_grade,
        failure_analysis=failure_analysis,
        git_info=get_git_status(),
    )
    pipeline.append(
        {
            "worker": "memory_manager",
            "category": "memory",
            "status": "done",
            "summary": project_memory.get("latest_output_dir", ""),
        }
    )

    state = finalize_state(root_job, interpretation, plan, pipeline, attempts, final_grade, project_memory)
    result = parse_jsonish(state.get("result"))
    result["parallel_upgrades"] = parallel_upgrades
    result["selection_attempts"] = selection_attempts
    result["git"] = get_git_status()
    state["result"] = result
    write_state(state)
    root_job.result = result
    upsert_job(root_job)
    return state


def run_once(prompt: str) -> dict[str, Any]:
    seed_memory = {}
    active = read_active_project()
    active_id = str(active.get("project_id") or "").strip()
    if active_id:
        seed_memory = read_project_memory(active_id)

    initial_interpretation = interpret_request(prompt, seed_memory)
    project_id = resolve_project_id(prompt, initial_interpretation)
    memory = read_project_memory(project_id)
    interpretation = interpret_request(prompt, memory)
    project_id = resolve_project_id(prompt, interpretation)
    if project_id != active_id:
        memory = read_project_memory(project_id)
        interpretation = interpret_request(prompt, memory)

    plan = build_execution_plan(interpretation, memory)
    root_job = register_job(prompt, interpretation, project_id)

    if interpretation.get("route_category") == "browser":
        pipeline: list[dict[str, Any]] = []
        processed = run_stage(
            prompt=prompt,
            category="browser",
            project_id=project_id,
            domain_mode=str(interpretation.get("domain_mode") or "general_mode"),
            goal=str(interpretation.get("goal_summary") or prompt),
            metadata={"interpretation": interpretation, "plan": plan},
            pipeline=pipeline,
        )
        browser_result = parse_jsonish(processed.result)
        grade = {
            "best_attempt_index": 0,
            "score": 70 if processed.status == "done" else 0,
            "status": "good" if processed.status == "done" else "blocked",
            "best_attempt": {"summary": processed.summary, "browser": browser_result},
            "attempt_comparison": [],
        }
        state = finalize_state(root_job, interpretation, plan, pipeline, [{"browser": browser_result, "summary": processed.summary}], grade, None)
        result = parse_jsonish(state.get("result"))
        result["git"] = get_git_status()
        state["result"] = result
        write_state(state)
        return state

    if interpretation.get("route_category") == "research":
        pipeline = []
        browser_context = {}
        browser_prompt = choose_browser_prompt(prompt, interpretation, 0, {})
        if browser_prompt:
            browsed = run_stage(
                prompt=browser_prompt,
                category="browser",
                project_id=project_id,
                domain_mode=str(interpretation.get("domain_mode") or "general_mode"),
                goal=str(interpretation.get("goal_summary") or prompt),
                metadata={"interpretation": interpretation, "plan": plan},
                pipeline=pipeline,
            )
            browser_context = parse_jsonish(browsed.result)
        processed = run_stage(
            prompt=prompt,
            category="research",
            project_id=project_id,
            domain_mode=str(interpretation.get("domain_mode") or "general_mode"),
            goal=str(interpretation.get("goal_summary") or prompt),
            metadata={"interpretation": interpretation, "plan": plan, "browser_context": browser_context},
            pipeline=pipeline,
        )
        grade = {
            "best_attempt_index": 0,
            "score": 60 if processed.status == "done" else 0,
            "status": "good" if processed.status == "done" else "blocked",
            "best_attempt": {"summary": processed.summary, "research": parse_jsonish(processed.result) or processed.result, "browser": browser_context},
            "attempt_comparison": [],
        }
        state = finalize_state(root_job, interpretation, plan, pipeline, [{"research": processed.result, "browser": browser_context, "summary": processed.summary}], grade, None)
        result = parse_jsonish(state.get("result"))
        result["git"] = get_git_status()
        state["result"] = result
        write_state(state)
        return state

    return run_coding_pipeline(root_job, interpretation, plan, memory)


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        print(json.dumps({"error": "prompt required"}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(run_once(prompt), ensure_ascii=False, indent=2))
