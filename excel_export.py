import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from datetime import datetime
from typing import List, Dict, Any, Union, Optional

def create_excel_report(records: List[Dict[str, Any]], output_target: Optional[Union[str, io.BytesIO]] = None) -> Union[str, io.BytesIO]:
    """
    Excel hisobotini yaratadi.
    Agar output_target berilmasa yoki io.BytesIO bo'lsa, xotirada (RAM) saqlab, io.BytesIO qaytaradi.
    Bu serverless va bulutli konteynerlarda diskka qaramlikni 100% yo'qotadi.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )

    def style_header(ws, fill, headers):
        ws.append(headers)
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = header_font
            cell.fill = fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

    # 1. Naqd Savdo
    ws_naqd = wb.create_sheet(title="Naqd Savdo")
    style_header(ws_naqd, PatternFill("solid", fgColor="2E7D32"), ["ID", "Sana", "Vaqt", "Mahsulot", "Miqdori", "Birligi", "Narxi", "Jami Summa", "Yuboruvchi"])

    # 2. Nasiya Savdo
    ws_nasiya = wb.create_sheet(title="Nasiya Savdo")
    style_header(ws_nasiya, PatternFill("solid", fgColor="C62828"), ["ID", "Sana", "Vaqt", "Mijoz", "Mahsulot", "Miqdori", "Birligi", "Narxi", "Jami Summa", "Yuboruvchi"])

    # 3. Pul Keldi (To'lovlar)
    ws_pul = wb.create_sheet(title="Pul Keldi (To'lovlar)")
    style_header(ws_pul, PatternFill("solid", fgColor="1565C0"), ["ID", "Sana", "Vaqt", "Mijoz", "Summa (So'm)", "Valyuta", "Dollar Miqdori", "Dollar Kursi", "Yuboruvchi"])

    # 4. Ombor Kelimi (Kirim)
    ws_kelim = wb.create_sheet(title="Ombor Kelimi")
    style_header(ws_kelim, PatternFill("solid", fgColor="00897B"), ["ID", "Sana", "Vaqt", "Mahsulot", "Miqdori", "Birligi", "Yetkazib beruvchi", "Yuboruvchi"])

    for r in records:
        cat = r.get("category")
        if cat == "naqd":
            ws_naqd.append([
                r.get("id"), r.get("date_str"), r.get("time_str"), r.get("item_name") or "",
                r.get("quantity") or 0, r.get("unit") or "", r.get("price") or 0,
                r.get("total_amount") or 0, r.get("sender_name") or ""
            ])
        elif cat == "nasiya":
            ws_nasiya.append([
                r.get("id"), r.get("date_str"), r.get("time_str"), r.get("partner_name") or "",
                r.get("item_name") or "", r.get("quantity") or 0, r.get("unit") or "",
                r.get("price") or 0, r.get("total_amount") or 0, r.get("sender_name") or ""
            ])
        elif cat in ("pul_keldi", "to'lov"):
            ws_pul.append([
                r.get("id"), r.get("date_str"), r.get("time_str"), r.get("partner_name") or "",
                r.get("total_amount") or 0, r.get("currency") or "UZS",
                r.get("amount_usd") or "", r.get("exchange_rate") or "", r.get("sender_name") or ""
            ])
        elif cat == "kelim":
            ws_kelim.append([
                r.get("id"), r.get("date_str"), r.get("time_str"), r.get("item_name") or "",
                r.get("quantity") or 0, r.get("unit") or "", r.get("partner_name") or "",
                r.get("sender_name") or ""
            ])

    for ws in [ws_naqd, ws_nasiya, ws_pul, ws_kelim]:
        ws.row_dimensions[1].height = 26
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                cell.border = thin_border
                cell.font = data_font if cell.row > 1 else header_font
                val_str = str(cell.value or "")
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    if output_target is None:
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer
    elif isinstance(output_target, io.BytesIO):
        wb.save(output_target)
        output_target.seek(0)
        return output_target
    else:
        wb.save(output_target)
        return output_target
