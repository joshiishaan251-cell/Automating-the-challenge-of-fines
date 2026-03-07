import sys
import os
import re
import yaml
import pdfplumber
import pandas as pd
from collections import defaultdict
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Обеспечиваем корректный вывод UTF-8 в консоль Windows
sys.stdout.reconfigure(encoding='utf-8')

# =========================================================
# 1. КОНФИГУРАЦИЯ И КОНТЕКСТ
# =========================================================
class StatementConfig:
    """Инкапсуляция всех настроек и правил проекта."""
    def __init__(self, config_path='config.yaml'):
        with open(config_path, encoding='utf-8') as f:
            c = yaml.safe_load(f)
        
        self.divider = c['scaling']['divider']
        self.inc_balance_orig = c['scaling']['incoming_balance']
        self.input_pdf = c['files']['input_pdf']
        self.output_pdf = c['files']['output_pdf']
        self.commissions = c.get('commission_exceptions') or []
        self.protected = c.get('protected_income') or []
        
        # Шрифты
        self.font_path = r"C:\Windows\Fonts\arial.ttf"
        self.font_bold_path = r"C:\Windows\Fonts\arialbd.ttf"
        self._register_fonts()

    def _register_fonts(self):
        if os.path.exists(self.font_path):
            pdfmetrics.registerFont(TTFont('Arial', self.font_path))
            self.has_custom_font = True
            if os.path.exists(self.font_bold_path):
                from reportlab.pdfbase.pdfmetrics import registerFontFamily
                pdfmetrics.registerFont(TTFont('Arial-Bold', self.font_bold_path))
                registerFontFamily('Arial', normal='Arial', bold='Arial-Bold')
        else:
            print("⚠️ ВНИМАНИЕ: Шрифт Arial не найден. Используем стандартный шрифт Helvetica (кириллица может не работать).")
            self.has_custom_font = False

# =========================================================
# 2. АГЕНТ: DataExtractor (Сборщик данных)
# =========================================================
class DataExtractor:
    """Отвечает за парсинг PDF, нормализацию таблиц и извлечение метаданных."""
    
    def extract(self, pdf_path):
        print("📄 DataExtractor: Читаем исходный PDF...")
        all_rows = []
        pdf_header_lines = []
        
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                tables = page.extract_tables() or []
                for table in tables:
                    if not table: continue
                    # Извлекаем шапку только с первой страницы
                    if page_num == 0 and not pdf_header_lines:
                        cell0 = table[0][0] if table[0] else ''
                        pdf_header_lines = [l.strip() for l in str(cell0 or '').split('\n') if l.strip()]
                    all_rows.extend(table)
            
            # Реквизиты из подвала последней страницы
            footer_bank_lines = []
            last_text = pdf.pages[-1].extract_text() or ''
            l_lines = [ln.strip() for ln in last_text.split('\n') if ln.strip()]
            try:
                fidx = next(i for i, ln in enumerate(l_lines) if 'исходящий остаток' in ln.lower())
                footer_bank_lines = l_lines[fidx + 1:]
            except StopIteration: pass

        df = self._normalize_table(all_rows)
        return df, pdf_header_lines, footer_bank_lines

    def _normalize_table(self, rows):
        """Приводит строки таблицы к единой длине и очищает от мусора."""
        if not rows: return pd.DataFrame()
        
        max_len = max((len(r) for r in rows if r), default=0)
        normalized = []
        for row in rows:
            if not row: continue
            r = list(row)
            if len(r) < max_len:
                diff = max_len - len(r)
                first = str(r[0]).strip() if r[0] is not None else ''
                if first and first.lower() not in ('none', 'nan', ''):
                    pad = diff // 2
                    r = [None] * pad + r + [None] * (diff - pad)
                else:
                    r = r + [None] * diff
            normalized.append(r)
            
        df = pd.DataFrame(normalized)
        # Поиск основной шапки (Дебет)
        h_idx = df[df.apply(lambda r: r.astype(str).str.contains('Дебет', na=False).any(), axis=1)].index
        if len(h_idx) > 0:
            df.columns = df.iloc[h_idx[0]].astype(str).str.replace('\n', ' ')
            df = df.iloc[h_idx[0] + 1:].reset_index(drop=True)
            
        # Очистка
        df = df[~df.apply(lambda r: r.astype(str).str.contains('Дебет', na=False).any(), axis=1)]
        df = df.dropna(how='all')
        non_empty = [c for c in df.columns if str(c).strip() not in ('', 'None', 'nan')]
        return df[non_empty].fillna("")

# =========================================================
# 3. АГЕНТ: FinancialScaler (Финансовый Трансформатор)
# =========================================================
class FinancialScaler:
    """Применяет бизнес-логику масштабирования и рассчитывает баланс."""
    
    def __init__(self, config):
        self.cfg = config

    def transform(self, df):
        print(f"🧮 FinancialScaler: Масштабируем суммы (divider={self.cfg.divider})...")
        
        col_d = next((c for c in df.columns if 'Дебет' in str(c)), 'Дебет')
        col_c = next((c for c in df.columns if 'Кредит' in str(c)), 'Кредит')
        col_p = next((c for c in df.columns if 'Назначение' in str(c)), 'Назначение платежа')
        col_n = next((c for c in df.columns if 'Название' in str(c)), '')

        rows_meta = []
        for idx, row in df.iterrows():
            d_raw = self._parse_num(row.get(col_d, ''))
            c_raw = self._parse_num(row.get(col_c, ''))
            purp  = str(row.get(col_p, ''))
            corr  = str(row.get(col_n, '')) if col_n else ''

            is_comm = self._matches(purp, d_raw, self.cfg.commissions)
            is_prot = (c_raw > 0) and self._matches(purp + ' ' + corr, c_raw, self.cfg.protected)
            
            rows_meta.append({'idx': idx, 'd': d_raw, 'c': c_raw, 'is_comm': is_comm, 'is_prot': is_prot})

        # Расчет распределения излишков от защищенных приходов
        additions = defaultdict(float)
        for i, m in enumerate(rows_meta):
            if m['is_prot']:
                excess = m['c'] - m['c'] / self.cfg.divider
                targets = [j for j in range(i+1, len(rows_meta)) 
                           if rows_meta[j]['d'] > 0 and not rows_meta[j]['is_comm'] and not rows_meta[j]['is_prot']]
                if targets:
                    share = excess / len(targets)
                    for j in targets: additions[j] += share

        # Финальный пересчет
        res_debits, res_credits = [], []
        d_cnt, c_cnt = 0, 0
        for i, m in enumerate(rows_meta):
            if m['is_comm']:
                nd, nc = m['d'], m['c']
            elif m['is_prot']:
                nd, nc = m['d'] / self.cfg.divider, m['c']
            else:
                nd = m['d'] / self.cfg.divider + additions.get(i, 0.0)
                nc = m['c'] / self.cfg.divider
            
            res_debits.append(nd)
            res_credits.append(nc)
            df.at[m['idx'], col_d] = self._format_num(nd) if nd > 0 else ""
            df.at[m['idx'], col_c] = self._format_num(nc) if nc > 0 else ""
            if nd > 0: d_cnt += 1
            if nc > 0: c_cnt += 1

        summary = {
            'd_docs': d_cnt, 'c_docs': c_cnt,
            'total_d': sum(res_debits), 'total_c': sum(res_credits),
            'in_balance': sum(res_debits) - sum(res_credits), # Для 0 в итоге
            'out_balance': 0.0
        }
        return df, summary

    def _parse_num(self, val):
        if pd.isna(val) or not str(val).strip(): return 0.0
        c = str(val).replace(' ', '').replace('\n', '').replace('\xa0', '').replace(',', '.')
        try: return float(c)
        except: return 0.0

    def _format_num(self, val):
        if val == 0 or pd.isna(val): return ""
        return f"{val:,.2f}".replace(',', 'X').replace('.', ',').replace('X', ' ')

    def _matches(self, text, amount, rules):
        t = re.sub(r'[\s\-]+', ' ', str(text).lower()).strip()
        for r in rules:
            p = re.sub(r'[\s\-]+', ' ', str(r.get('payer', '')).lower()).strip()
            if p in t:
                ra = r.get('amount')
                if ra is None or abs(amount - float(ra)) < 0.01: return True
        return False

# =========================================================
# 4. АГЕНТ: ReportRenderer (Генератор Отчетов)
# =========================================================
class ReportRenderer:
    """Генератор финального PDF с соблюдением всех стилистических правил."""
    
    def __init__(self, config):
        self.cfg = config
        self.W = 782
        self.FS = 6.96
        self.LD = 8.5
        self._init_styles()

    def _init_styles(self):
        font_base = 'Arial' if getattr(self.cfg, 'has_custom_font', False) else 'Helvetica'
        font_bold = 'Arial-Bold' if getattr(self.cfg, 'has_custom_font', False) else 'Helvetica-Bold'
        
        self.sN  = ParagraphStyle('sN',  fontName=font_base, fontSize=self.FS, leading=self.LD, wordWrap='CJK')
        self.sNB = ParagraphStyle('sNB', fontName=font_bold, fontSize=self.FS, leading=self.LD, wordWrap='CJK')
        self.sL  = ParagraphStyle('sL',  fontName=font_base, fontSize=self.FS, leading=self.LD)
        self.sLB = ParagraphStyle('sLB', fontName=font_bold, fontSize=self.FS, leading=self.LD)
        self.sC  = ParagraphStyle('sC',  fontName=font_base, fontSize=self.FS, leading=self.LD, alignment=1)
        self.sCB = ParagraphStyle('sCB', fontName=font_bold, fontSize=self.FS, leading=self.LD, alignment=1)
        self.sR  = ParagraphStyle('sR',  fontName=font_base, fontSize=self.FS, leading=self.LD, alignment=2)
        self.sRB = ParagraphStyle('sRB', fontName=font_bold, fontSize=self.FS, leading=self.LD, alignment=2)
        self.sCH = ParagraphStyle('sCH', fontName=font_bold, fontSize=7.5,     leading=9,       alignment=1)
        self.sStamp = ParagraphStyle('sStamp', fontName=font_base, fontSize=self.FS, leading=self.LD, alignment=1)

    def render(self, df, summary, header_lines, footer_bank_lines):
        print(f"🎨 ReportRenderer: Генерация PDF -> {self.cfg.output_pdf}")
        doc = SimpleDocTemplate(self.cfg.output_pdf, pagesize=landscape(A4),
                                rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        elements = []

        # --- Шапка документа ---
        self._add_header(elements, header_lines, summary['in_balance'])
        
        # --- Основная таблица ---
        self._add_main_table(elements, df)
        
        # --- Подвал с итогами ---
        self._add_footer_summary(elements, summary)
        
        # --- Банковский штамп ---
        self._add_bank_footer(elements, footer_bank_lines)

        doc.build(elements)
        print("✅ Рендеринг завершен!")

    def _add_header(self, el, lines, in_bal):
        def _f(kw): return next((l for l in lines if kw.lower() in l.lower()), '')
        
        bank = _f('мсп банк')
        ts   = next((l for l in lines if re.match(r'\d{2}\.\d{2}\.\d{4}', l)), '')
        if bank: el.append(Paragraph(f'<b>{bank}</b>', self.sL))
        if ts:   el.append(Paragraph(ts, self.sL))
        el.append(Spacer(1, 6))

        title  = _f('выписка')
        period = _f('за период')
        acc_l  = _f('счет ')
        cur    = ''
        m = re.match(r'СЧЕТ\s+(\S+)\s*(.*)', acc_l, re.IGNORECASE)
        if m: acc_num, cur = m.group(1), m.group(2).strip()
        
        if title:  el.append(Paragraph(f'<b>{title}</b>', self.sCB))
        if period: el.append(Paragraph(period, self.sC))
        if cur:    el.append(Paragraph(cur, self.sC))
        el.append(Spacer(1, 4))

        # СЧЕТ / НАЗВАНИЕ
        name_l = _f('название ')
        p_name = m.group(1).strip() if (m := re.match(r'НАЗВАНИЕ\s+(.*)', name_l, re.IGNORECASE)) else ''
        
        rows = []
        if 'acc_num' in locals(): rows.append([Paragraph('<b>СЧЕТ</b>', self.sLB), Paragraph(acc_num, self.sL)])
        if p_name: rows.append([Paragraph('<b>НАЗВАНИЕ</b>', self.sLB), Paragraph(p_name, self.sL)])
        if rows:
            t = Table(rows, colWidths=[80, self.W-80])
            t.setStyle(TableStyle([('TOPPADDING',(0,0),(-1,-1),1), ('BOTTOMPADDING',(0,0),(-1,-1),1)]))
            el.append(t)
        
        # Дата предыд. операции
        prev_l = _f('дата предыдущей')
        if prev_l:
            parts = prev_l.rsplit(' ', 1)
            t_p = Table([[Paragraph(parts[0], self.sL), Paragraph(parts[1] if len(parts)>1 else '', self.sL)]], colWidths=[260, self.W-260])
            el.append(t_p)

        # Входящий остаток
        cw = [50, 25, 38, 90, 83, 95, 95, 48, 48, 210]
        l_w, v_w = sum(cw[:5]), sum(cw[5:7])
        val_str = f"{in_bal:,.2f}".replace(',', 'X').replace('.', ',').replace('X', ' ') + ' (П)'
        t_b = Table([[Paragraph('<b>Входящий остаток</b>    пассив', self.sLB), Paragraph(val_str, self.sRB), '']], 
                    colWidths=[l_w, v_w, self.W - l_w - v_w])
        t_b.setStyle(TableStyle([('TOPPADDING',(0,0),(-1,-1),2), ('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        el.append(t_b)

    def _add_main_table(self, el, df):
        data = [[Paragraph(col, self.sCH) for col in df.columns]]
        for row in df.values:
            cells = []
            for i, c in enumerate(row):
                # Распределение стилей:
                # 7-8: Справа (Дебет, Кредит)
                # Остальное: Слева (sN)
                style = self.sR if i in (7, 8) else self.sN
                cells.append(Paragraph(str(c).replace('\n', '<br/>'), style))
            data.append(cells)
        
        cw = [50, 25, 38, 90, 83, 95, 95, 48, 48, 210] if len(df.columns) == 10 else [self.W/len(df.columns)]*len(df.columns)
        t = Table(data, colWidths=cw, repeatRows=0)
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f2f2f2')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 2),
            ('RIGHTPADDING', (0,0), (-1,-1), 2),
            ('TOPPADDING', (0,0), (-1,-1), 1),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ]))
        el.append(t)

    def _add_footer_summary(self, el, s):
        def _fmt(v): return f"{v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', ' ')
        cw = [50, 25, 38, 90, 83, 95, 95, 48, 48, 210]
        # Исходящий остаток: метка до колонки Кредит, сумма в колонке Кредит
        fd = [
            [Paragraph('Документов', self.sL), '', '', '', '', '', '', Paragraph(str(s['d_docs']), self.sR), Paragraph(str(s['c_docs']), self.sR), ''],
            [Paragraph('Итого обороты', self.sL), '', '', '', '', '', '', Paragraph(_fmt(s['total_d']), self.sR), Paragraph(_fmt(s['total_c']), self.sR), ''],
            [Paragraph('<b>Исходящий остаток</b>    пассив', self.sLB), '', '', '', '', '', '', '', Paragraph(_fmt(s['out_balance'])+' (П)', self.sRB), ''],
        ]
        ft = Table(fd, colWidths=cw)
        ft.setStyle(TableStyle([
            ('SPAN',(0,0),(6,0)),
            ('SPAN',(0,1),(6,1)),
            ('SPAN',(0,2),(7,2)), # Метка занимает всё до Дебета/Кредита
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 2),
            ('TOPPADDING', (0,0), (-1,-1), 1),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ]))
        el.append(ft)

    def _add_bank_footer(self, el, lines):
        # Жестко формируем последовательность по требованию
        # 1. АО "МСП БАНК" г.МОСКВА БИК 044525108 корсчет
        # 2. 30101810200000000108 ПРОВЕДЕНО
        bik = next((re.search(r'\d{9}', l).group(0) for l in lines if 'БИК' in l.upper()), '044525108')
        acc = next((re.search(r'\d{20}', l).group(0) for l in lines if re.search(r'\d{20}', l)), '30101810200000000108')
        
        line1 = f'АО "МСП БАНК" г.МОСКВА БИК {bik} корсчет'
        line2 = f'{acc} ПРОВЕДЕНО'
        full_text = f"{line1}<br/>{line2}"

        if full_text:
            # Уменьшаем ширину до 185px для максимальной плотности рамки
            t = Table([['', Paragraph(full_text, self.sStamp)]], colWidths=[self.W-185, 185])
            t.setStyle(TableStyle([
                ('BOX',           (1,0), (1,0), 1.5, colors.black),
                ('LEFTPADDING',   (1,0), (1,0), 3),
                ('RIGHTPADDING',  (1,0), (1,0), 3),
                ('TOPPADDING',    (1,0), (1,0), 3),
                ('BOTTOMPADDING', (1,0), (1,0), 3),
                ('ALIGN',         (1,0), (1,0), 'CENTER'),
                ('VALIGN',        (1,0), (1,0), 'MIDDLE'),
            ]))
            el.append(t)

# =========================================================
# 5. ОРКЕСТРАТОР (Pipeline)
# =========================================================
class ProcessingPipeline:
    def __init__(self):
        self.cfg = StatementConfig()
        self.extractor = DataExtractor()
        self.scaler = FinancialScaler(self.cfg)
        self.renderer = ReportRenderer(self.cfg)

    def run(self):
        try:
            if not os.path.exists(self.cfg.input_pdf):
                abs_path = os.path.abspath(self.cfg.input_pdf)
                print(f"❌ ОШИБКА: Файл выписки не найден по пути: {abs_path}")
                print("Пожалуйста, проверьте путь в config.yaml или наличие файла.")
                return

            df_raw, header, footer = self.extractor.extract(self.cfg.input_pdf)
            df_final, summary = self.scaler.transform(df_raw)
            self.renderer.render(df_final, summary, header, footer)
            print("🚀 Сценарий успешно завершен!")
        except Exception as e:
            import traceback
            print(f"❌ Критическая ошибка пайплайна: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    ProcessingPipeline().run()