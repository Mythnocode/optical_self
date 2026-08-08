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
            message="job not found",
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
            message="job not found",
            context={"job_id": job_id},
        )
    except RuntimeError:
        return failure(
            request,
            status_code=409,
            code="JOB_RESULT_NOT_AVAILABLE",
            stage="job.result",
            message="job result is not available",
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
            message="job not found", context={"job_id": job_id},
        )
    except RuntimeError:
        return failure(
            request, status_code=409, code="JOB_RESULT_NOT_AVAILABLE", stage="job.result.summary",
            message="job result is not available", context={"job_id": job_id},
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
            message="job not found", context={"job_id": job_id},
        )
    except RuntimeError:
        return failure(
            request, status_code=409, code="JOB_LIVE_RESULT_NOT_AVAILABLE", stage="job.result.local",
            message="local live result is not available", context={"job_id": job_id},
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
            message="job not found", context={"job_id": job_id, "analysis": analysis},
        )
    except KeyError:
        return failure(
            request, status_code=404, code="ANALYSIS_NOT_FOUND", stage="job.result.analysis",
            message="analysis result is not available", context={"job_id": job_id, "analysis": analysis},
        )
    except RuntimeError:
        return failure(
            request, status_code=409, code="JOB_RESULT_NOT_AVAILABLE", stage="job.result.analysis",
            message="job result is not available", context={"job_id": job_id, "analysis": analysis},
        )


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
            message="job not found",
            context={"job_id": job_id},
        )

    if existing_status.status not in ("queued", "running"):
        return failure(
            request,
            status_code=409,
            code="JOB_CANNOT_CANCEL",
            stage="job.cancel",
            message=f"job is in '{existing_status.status}' state and cannot be cancelled",
            context={"job_id": job_id, "current_status": existing_status.status},
        )

    if not task_manager.cancel(job_id):
        return failure(
            request,
            status_code=500,
            code="CANCEL_FAILED",
            stage="job.cancel",
            message="failed to cancel job",
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
        message="cancel request accepted",
    )
