from fastapi import APIRouter, Query, Request, status

from backend.optical_ml_app.api.responses import failure, success


router = APIRouter()


@router.get("/jobs")
def list_jobs(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    job_type: str | None = None,
):

    return success(
        request,
        request.app.state.services["task_manager"].list_jobs(
            limit=limit, offset=offset, status=status, job_type=job_type,
        ),
    )


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    try:
        return success(request, request.app.state.services["task_manager"].get_status(job_id))
    except FileNotFoundError:
        return failure(
            request,
            status_code=404,
            code="JOB_NOT_FOUND",
            stage="job.lookup",
            message="未找到任务",
            context={"job_id": job_id},
        )


@router.get("/jobs/{job_id}/result")
def get_result(job_id: str, request: Request):
    try:
        return success(request, request.app.state.services["task_manager"].get_result(job_id))
    except FileNotFoundError:
        return failure(
            request,
            status_code=404,
            code="JOB_NOT_FOUND",
            stage="job.result",
            message="未找到任务",
            context={"job_id": job_id},
        )
    except RuntimeError:
        return failure(
            request,
            status_code=409,
            code="JOB_RESULT_NOT_AVAILABLE",
            stage="job.result",
            message="任务尚无可用正式结果",
            context={"job_id": job_id},
        )


@router.get("/jobs/{job_id}/result-summary")
def get_result_summary(job_id: str, request: Request):
    try:
        return success(
            request,
            request.app.state.services["task_manager"].get_result_summary(job_id),
        )
    except FileNotFoundError:
        return failure(
            request, status_code=404, code="JOB_NOT_FOUND", stage="job.result.summary",
            message="未找到任务", context={"job_id": job_id},
        )
    except RuntimeError:
        return failure(
            request, status_code=409, code="JOB_RESULT_NOT_AVAILABLE", stage="job.result.summary",
            message="任务尚无可用正式结果", context={"job_id": job_id},
        )


@router.get("/jobs/{job_id}/live-result-local")
def get_live_result_local(job_id: str, request: Request):

    try:
        return success(
            request,
            request.app.state.services["task_manager"].get_live_result_local(job_id),
        )
    except FileNotFoundError:
        return failure(
            request, status_code=404, code="JOB_NOT_FOUND", stage="job.result.local",
            message="未找到任务", context={"job_id": job_id},
        )
    except RuntimeError:
        return failure(
            request, status_code=409, code="JOB_LIVE_RESULT_NOT_AVAILABLE", stage="job.result.local",
            message="任务尚无可用实时结果", context={"job_id": job_id},
        )


@router.get("/jobs/{job_id}/result/{analysis}")
def get_result_analysis(job_id: str, analysis: str, request: Request):
    try:
        return success(
            request,
            request.app.state.services["task_manager"].get_result_analysis(job_id, analysis),
        )
    except FileNotFoundError:
        return failure(
            request, status_code=404, code="JOB_NOT_FOUND", stage="job.result.analysis",
            message="未找到任务", context={"job_id": job_id, "analysis": analysis},
        )
    except KeyError:
        return failure(
            request, status_code=404, code="ANALYSIS_NOT_FOUND", stage="job.result.analysis",
            message="指定分析结果不可用", context={"job_id": job_id, "analysis": analysis},
        )
    except RuntimeError:
        return failure(
            request, status_code=409, code="JOB_RESULT_NOT_AVAILABLE", stage="job.result.analysis",
            message="任务尚无可用正式结果", context={"job_id": job_id, "analysis": analysis},
        )


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_job(job_id: str, request: Request):
    task_manager = request.app.state.services["task_manager"]
    try:
        retried = task_manager.retry(job_id)
    except FileNotFoundError:
        return failure(request, status_code=409, code="JOB_RETRY_NOT_AVAILABLE", stage="job.retry",
            message="该任务没有可重放的提交信息，请返回原功能页重新提交", retryable=False, context={"job_id": job_id})
    except PermissionError:
        return failure(request, status_code=409, code="JOB_NOT_RETRYABLE", stage="job.retry",
            message="该失败类型不建议直接重试，请先修正失败原因", retryable=False, context={"job_id": job_id})
    except ValueError:
        return failure(request, status_code=409, code="JOB_CANNOT_RETRY", stage="job.retry",
            message="只有失败或已取消的任务可以重新运行", retryable=False, context={"job_id": job_id})
    except Exception as exc:
        return failure(request, status_code=500, code="JOB_RETRY_FAILED", stage="job.retry",
            message=f"重新提交任务失败：{exc}", retryable=True, context={"job_id": job_id})
    return success(request, retried, status_code=status.HTTP_202_ACCEPTED, message="任务已重新提交")


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    task_manager = request.app.state.services["task_manager"]

    
    try:
        existing_status = task_manager.get_status(job_id)
    except FileNotFoundError:
        existing_status = None

    if existing_status is None:
        return failure(
            request,
            status_code=404,
            code="JOB_NOT_FOUND",
            stage="job.cancel",
            message="未找到任务",
            context={"job_id": job_id},
        )

    if existing_status.status not in ("queued", "running"):
        return failure(
            request,
            status_code=409,
            code="JOB_CANNOT_CANCEL",
            stage="job.cancel",
            message=f"任务当前状态为 {existing_status.status}，不能取消",
            context={"job_id": job_id, "current_status": existing_status.status},
        )

    if not task_manager.cancel(job_id):
        return failure(
            request,
            status_code=500,
            code="CANCEL_FAILED",
            stage="job.cancel",
            message="取消任务失败",
            context={"job_id": job_id},
        )

    job_status = task_manager.get_status(job_id)
    return success(
        request,
        {
            "job_id": job_id,
            "cancel_requested": True,
            "status": job_status.status,
        },
        status_code=status.HTTP_202_ACCEPTED,
        message="已接受取消请求",
    )
