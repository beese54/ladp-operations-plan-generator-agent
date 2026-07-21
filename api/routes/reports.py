import logging

from fastapi import APIRouter, HTTPException, Response

from reporting.pdf_report import (
    ReportGenerationError,
    ReportNotFoundError,
    build_operation_report_pdf,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/operations/{operation_id}/report")
async def get_operation_report(operation_id: str) -> Response:
    try:
        pdf_bytes = build_operation_report_pdf(operation_id)
    except ReportNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ReportGenerationError as e:
        logger.exception("Report generation failed for %s", operation_id)
        raise HTTPException(status_code=500, detail=str(e))

    filename = f"{operation_id}_isolation_report.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
