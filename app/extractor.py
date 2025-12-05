import fitz  # PyMuPDF

def extract_raw_pages(pdf_path: str):
    doc = fitz.open(pdf_path)
    pages = []

    for i in range(len(doc)):
        page = doc[i]
        blocks = page.get_text("dict")["blocks"]

        page_data = {
            "page": i + 1,
            "items": []
        }

        for b in blocks:
            if b["type"] == 0:
                for line in b["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if text:
                            page_data["items"].append({
                                "text": text,
                                "bbox": span["bbox"]
                            })

        pages.append(page_data)

    return pages

