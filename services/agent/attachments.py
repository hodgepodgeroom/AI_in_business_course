"""Извлечение текста из файлов заявки."""

import io, zipfile
import xml.etree.ElementTree as ET


def read_attachment(data, name):
    ext = name.rsplit(".", 1)[-1].lower()
    if ext in ("txt", "csv", "json"):
        return data.decode("utf-8-sig", errors="replace")[:35000]
    if ext == "pdf":
        from pypdf import PdfReader

        pdf = PdfReader(io.BytesIO(data))
        return "\n".join(p.extract_text() or "" for p in pdf.pages[:20])[:35000]
    if ext == "xlsx":
        import openpyxl

        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        lines = []
        for sheet in book:
            lines.append("Лист: " + sheet.title)
            for n, row in enumerate(sheet.iter_rows(values_only=True)):
                if n >= 500:
                    break
                lines.append(" | ".join("" if x is None else str(x) for x in row[:25]))
        book.close()
        return "\n".join(lines)[:35000]
    if ext == "docx":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.getinfo("word/document.xml").file_size > 10000000:
                raise ValueError("Слишком большой документ")
            root = ET.fromstring(z.read("word/document.xml"))
            return " ".join(root.itertext())[:35000]
    if ext in ("png", "jpg", "jpeg"):
        return ""
    raise ValueError("Формат не поддержан")
