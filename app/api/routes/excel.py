from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services.excel_service import ExcelService

router = APIRouter()


@router.post("/upload-excel")
async def upload_excel(file: UploadFile = File(...)):
    """Upload Excel file and return data as JSON records."""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="File must be an Excel file (.xlsx or .xls)")

    try:
        excel_service = ExcelService()
        result = excel_service.read_excel(file)
        return result

    except Exception as e:
        import traceback
        print(f"\n{'='*80}")
        print(f"ERROR in upload_excel:")
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception message: {str(e)}")
        print(f"Traceback:")
        traceback.print_exc()
        print(f"{'='*80}\n")
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")
