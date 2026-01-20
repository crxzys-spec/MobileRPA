
def build_ocr_structure_views(raw_result):
    pages = raw_result if isinstance(raw_result, list) else [raw_result]
    ocr_pages = []
    structure_pages = []
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        width = page.get("width")
        height = page.get("height")
        ocr_pages.append(
            {
                "page_index": index,
                "width": width,
                "height": height,
                "overall_ocr_res": page.get("overall_ocr_res") or {},
            }
        )
        structure_pages.append(
            {
                "page_index": index,
                "width": width,
                "height": height,
                "doc_preprocessor_res": page.get("doc_preprocessor_res"),
                "layout_det_res": page.get("layout_det_res"),
                "region_det_res": page.get("region_det_res"),
                "imgs_in_doc": page.get("imgs_in_doc"),
                "table_res_list": page.get("table_res_list"),
                "seal_res_list": page.get("seal_res_list"),
                "chart_res_list": page.get("chart_res_list"),
                "formula_res_list": page.get("formula_res_list"),
                "parsing_res_list": page.get("parsing_res_list"),
                "model_settings": page.get("model_settings"),
            }
        )
    return {"pages": ocr_pages}, {"pages": structure_pages}
