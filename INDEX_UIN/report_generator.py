import openpyxl
from openpyxl.styles import Font, Alignment
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def generate_excel_report(self, output_path):
        """Generate a dual-sheet Excel report: All UINs and Duplicates."""
        try:
            wb = openpyxl.Workbook()
            
            # Sheet 1: All UINs
            ws_all = wb.active
            ws_all.title = "Все УИН"
            headers = ["УИН", "Имя файла в архиве", "Путь к архиву", "Дата нахождения"]
            ws_all.append(headers)
            
            # Format headers
            for cell in ws_all[1]:
                cell.font = Font(bold=True)
            
            # Fetch all occurrences
            with self.db_manager._connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT u.number, o.filename, a.path, o.discovery_date
                    FROM occurrences o
                    JOIN uins u ON o.uin_id = u.id
                    JOIN archives a ON o.archive_id = a.id
                    ORDER BY u.number
                ''')
                for row in cursor.fetchall():
                    ws_all.append(row)

            # Sheet 2: Duplicates
            ws_dupes = wb.create_sheet("Повторяющиеся УИН")
            ws_dupes.append(["УИН", "Кол-во повторов", "Список локаций (Архив -> Файл)"])
            
            for cell in ws_dupes[1]:
                cell.font = Font(bold=True)

            with self.db_manager._connection() as conn:
                cursor = conn.cursor()
                # Find duplicates
                cursor.execute('''
                    SELECT u.number, COUNT(o.uin_id) as count
                    FROM occurrences o
                    JOIN uins u ON o.uin_id = u.id
                    GROUP BY o.uin_id
                    HAVING count > 1
                    ORDER BY count DESC
                ''')
                dupes = cursor.fetchall()
                
                for uin_number, count in dupes:
                    # Get locations for this UIN
                    cursor.execute('''
                        SELECT a.path, o.filename
                        FROM occurrences o
                        JOIN archives a ON o.archive_id = a.id
                        JOIN uins u ON o.uin_id = u.id
                        WHERE u.number = ?
                    ''', (uin_number,))
                    locations = [f"{os.path.basename(path)} ({filename})" for path, filename in cursor.fetchall()]
                    ws_dupes.append([uin_number, count, ", ".join(locations)])

            # Auto-adjust column width
            for ws in [ws_all, ws_dupes]:
                for col in ws.columns:
                    max_length = 0
                    column = col[0].column_letter
                    for cell in col:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except: pass
                    ws.column_dimensions[column].width = min(max_length + 2, 50)

            wb.save(output_path)
            logger.info(f"Excel-отчет успешно сохранен: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при создании Excel-отчета: {e}")
            return False

import os
