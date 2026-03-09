import os
import tempfile
import openpyxl
import logging

logger = logging.getLogger(__name__)

# Fetch this many rows at a time from SQLite
_CHUNK = 1000


class ReportGenerator:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def generate_excel_report(self, output_path):
        """
        Generate a dual-sheet Excel report.

        Fix #6: Saves to a temp file first, then atomically renames to output_path
        via os.replace(). This prevents a partially-written (corrupt) .xlsx
        if the process is interrupted mid-save.
        """
        report_dir = os.path.dirname(output_path) or '.'
        tmp_path = None
        try:
            # Write to a temp file in the same directory so os.replace() is atomic
            fd, tmp_path = tempfile.mkstemp(dir=report_dir, suffix='.tmp.xlsx')
            os.close(fd)

            wb = openpyxl.Workbook()

            # ── Sheet 1: All UINs ──────────────────────────────────────
            ws_all = wb.active
            ws_all.title = "Все УИН"
            ws_all.append([
                "УИН",
                "Имя файла в архиве / путь к файлу",
                "Путь к архиву",
                "Дата нахождения",
                "Перемещен"
            ])

            with self.db_manager._connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT
                        u.number,
                        o.filename,
                        a.path,
                        o.discovery_date,
                        COALESCE(a.moved_to, '') AS moved_to
                    FROM occurrences o
                    JOIN uins u ON o.uin_id = u.id
                    JOIN archives a ON o.archive_id = a.id
                    ORDER BY u.number
                ''')
                while True:
                    rows = cursor.fetchmany(_CHUNK)
                    if not rows:
                        break
                    for row in rows:
                        ws_all.append(row)

            # ── Sheet 2: Duplicates ────────────────────────────────────
            ws_dupes = wb.create_sheet("Повторяющиеся УИН")
            ws_dupes.append([
                "УИН",
                "Кол-во повторов",
                "Места нахождения (Архив -> Файл)",
                "Перемещен"
            ])

            with self.db_manager._connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT
                        u.number,
                        COUNT(*) AS cnt,
                        GROUP_CONCAT(a.path || ' (' || o.filename || ')', ' | '),
                        GROUP_CONCAT(
                            CASE WHEN a.moved_to IS NOT NULL
                                 THEN a.path || ' → ' || a.moved_to
                                 ELSE NULL
                            END, ' | '
                        )
                    FROM occurrences o
                    JOIN uins u ON o.uin_id = u.id
                    JOIN archives a ON o.archive_id = a.id
                    GROUP BY o.uin_id
                    HAVING cnt > 1
                    ORDER BY cnt DESC
                ''')
                while True:
                    rows = cursor.fetchmany(_CHUNK)
                    if not rows:
                        break
                    for row in rows:
                        ws_dupes.append(row)

            # Save to temp, then atomically replace — no corrupt file on interruption
            wb.save(tmp_path)
            os.replace(tmp_path, output_path)
            tmp_path = None  # Mark as consumed so finally doesn't delete it

            logger.info(f"Excel-отчет успешно сохранен: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при создании Excel-отчета: {e}")
            return False
        finally:
            # Clean up temp file if something went wrong before os.replace()
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
