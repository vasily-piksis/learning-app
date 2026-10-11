def source_data(document, page, include_text=False):
    value = {
        "page_id": page.id,
        "document_id": document.id,
        "name": document.name,
        "page": page.number,
        "language": page.language or document.source_meta.get("language"),
    }
    if document.source_url and page.start_seconds is not None:
        value.update(
            url=f"{document.source_url}&t={int(page.start_seconds)}",
            start_seconds=page.start_seconds,
            end_seconds=page.end_seconds,
        )
    if include_text:
        value["text"] = page.text
    return value
