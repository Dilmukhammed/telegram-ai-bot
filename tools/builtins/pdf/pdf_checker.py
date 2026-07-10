from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_LIVE_FETCH,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    FETCH_PDF_READ_METADATA,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_LIVE_PDF_METADATA = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_PDF_READ_METADATA,
    label="pdf_metadata_live",
)

_PRIOR_PDF_FILE_REF = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "google.drive.download_file",
        "google.drive.export_file",
        "pdf.split",
        "pdf.extract_pages",
        "pdf.merge",
        "pdf.create",
        "pdf.create_from_images",
        "pdf.create_blank",
    ),
    match=(("file_ref", "$call.file_ref"),),
    optional=True,
    max_age_steps=10,
    label="prior_pdf_file_ref",
)

_PRIOR_PDF_PATH = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("workspace.stat", "workspace.read_file", "workspace.import_from_file_ref"),
    match=(("path", "$call.path"),),
    optional=True,
    max_age_steps=10,
    label="prior_pdf_path",
)

_PRIOR_PDF_READ = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="pdf.*",
    optional=True,
    max_age_steps=10,
    label="prior_pdf_read",
)

_PRIOR_FORM_FIELDS = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("pdf.extract_forms", "pdf.fill_form"),
    match=(("file_ref", "$call.file_ref"), ("path", "$call.path")),
    optional=True,
    max_age_steps=10,
    label="prior_form_fields",
)


def _call(label: str, *fields: str) -> EvidenceRef:
    return EvidenceRef(kind=EVIDENCE_CALL, fields=fields, label=label)


def _input_evidence(*fields: str) -> tuple[EvidenceRef, ...]:
    return (
        _call("pdf_input_call", *fields),
        _USER_GOAL,
        _PRIOR_PDF_FILE_REF,
        _PRIOR_PDF_PATH,
        _PRIOR_PDF_READ,
    )


# --- Read: extract / metadata ---

PDF_EXTRACT_TEXT_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF the user asked to read?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages"),
    ),
    VerificationQuestion(
        id="pages_scope",
        text="Does pages limit extraction to the pages the user asked for?",
        severity=SEVERITY_WARN,
        evidence=(_call("extract_text_call", "pages"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="ocr_not_needed",
        text="If text is empty/garbled, should is_scanned or ocr have been tried first?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL, _PRIOR_PDF_READ),
    ),
)

PDF_EXTRACT_TABLES_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF the user asked to extract tables from?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages", "strategy"),
    ),
    VerificationQuestion(
        id="strategy_matches_layout",
        text="Does strategy (lines/text/strings) fit the table layout in the document?",
        severity=SEVERITY_WARN,
        evidence=(_call("extract_tables_call", "strategy"), _USER_GOAL),
    ),
)

PDF_EXTRACT_IMAGES_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose images the user asked to extract?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages", "output"),
    ),
    VerificationQuestion(
        id="output_mode_matches",
        text="Does output (vision/file_ref/both) match how the user wants images delivered?",
        severity=SEVERITY_WARN,
        evidence=(_call("extract_images_call", "output"), _USER_GOAL),
    ),
)

PDF_READ_METADATA_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose metadata the user asked to inspect?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path"),
    ),
)

PDF_GET_OUTLINE_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose bookmarks/outline the user asked for?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path"),
    ),
)

PDF_SEARCH_TEXT_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF to search?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "query", "pages"),
    ),
    VerificationQuestion(
        id="query_matches_intent",
        text="Does query match the text the user asked to find?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("search_text_call", "query", "case_sensitive", "whole_words"), _USER_GOAL),
    ),
)

PDF_GET_PAGE_INFO_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose page info the user asked for?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages"),
    ),
)

PDF_EXTRACT_LINKS_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose links the user asked to extract?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages"),
    ),
)

PDF_EXTRACT_FORMS_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF form the user asked to inspect?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path"),
    ),
    VerificationQuestion(
        id="forms_before_fill",
        text="If fill_form follows, does this read cover the fields to be set?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
)

PDF_OCR_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the scanned PDF the user asked to OCR?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages", "lang"),
    ),
    VerificationQuestion(
        id="ocr_justified",
        text="Was OCR needed (is_scanned or failed extract_text), not plain extract_text on text PDF?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _PRIOR_PDF_READ),
    ),
)

PDF_IS_SCANNED_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF the user asked to classify as scanned vs text?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages"),
    ),
)

PDF_RENDER_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose pages the user asked to visualize?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages", "output"),
    ),
    VerificationQuestion(
        id="pages_and_quality",
        text="Do pages and dpi/scale match what the user asked to see (max 20 pages)?",
        severity=SEVERITY_WARN,
        evidence=(_call("render_call", "pages", "dpi", "scale", "output"), _USER_GOAL),
    ),
)

PDF_GET_PERMISSIONS_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose encryption/permissions the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "password"),
    ),
)

# --- Write: pages ---

PDF_SPLIT_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF the user asked to split?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages", "every_n_pages"),
    ),
    VerificationQuestion(
        id="split_groups_match",
        text="Do pages groups or every_n_pages match how the user wanted parts divided?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("split_call", "pages", "every_n_pages"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="split_not_extract",
        text="Did the user want multiple output files (split), not one extracted subset?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
)

PDF_EXTRACT_PAGES_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the source PDF?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages"),
    ),
    VerificationQuestion(
        id="pages_match_intent",
        text="Does pages list exactly the pages the user asked to keep in the new PDF?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("extract_pages_call", "pages"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="output_pdf_live",
        text="Does live read_metadata on the output file_ref show a valid PDF?",
        severity=SEVERITY_WARN,
        evidence=(_call("extract_pages_call", "pages"), _LIVE_PDF_METADATA, _USER_GOAL),
    ),
)

PDF_MERGE_QUESTIONS = (
    VerificationQuestion(
        id="file_refs_order",
        text="Are file_refs in the order the user asked to combine documents?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("merge_call", "file_refs"), _USER_GOAL, _PRIOR_PDF_READ),
    ),
    VerificationQuestion(
        id="all_inputs_present",
        text="Does file_refs include every PDF the user asked to merge?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("merge_call", "file_refs"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="merged_pdf_live",
        text="Does live read_metadata confirm the merged output PDF exists?",
        severity=SEVERITY_WARN,
        evidence=(_LIVE_PDF_METADATA, _USER_GOAL),
    ),
)

PDF_ROTATE_PAGES_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose pages the user asked to rotate?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages"),
    ),
    VerificationQuestion(
        id="rotation_map_correct",
        text="Does the pages→angle map match the rotations the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("rotate_call", "pages"), _USER_GOAL),
    ),
)

PDF_DELETE_PAGES_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF the user asked to remove pages from?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "pages"),
    ),
    VerificationQuestion(
        id="pages_to_delete_match",
        text="Does pages list only the pages the user asked to delete (not keep)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_pages_call", "pages"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="delete_not_extract",
        text="Did the user want pages removed from a copy, not extract-only subset?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
)

PDF_REORDER_PAGES_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose page order the user asked to change?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "order", "swap"),
    ),
    VerificationQuestion(
        id="reorder_spec_valid",
        text="Does order (full permutation) or swap match the reorder the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("reorder_call", "order", "swap"), _USER_GOAL),
    ),
)

# --- Write: edit / overlay ---

PDF_OVERLAY_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF to stamp text on?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "content", "mode", "pages"),
    ),
    VerificationQuestion(
        id="overlay_content_mode",
        text="Do content, mode, and position match watermark/header/footer/page_numbers intent?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("overlay_call", "content", "mode", "position", "format"), _USER_GOAL),
    ),
)

PDF_REDACT_TEXT_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF the user asked to redact?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "query", "pages"),
    ),
    VerificationQuestion(
        id="redact_query_scope",
        text="Does query target the sensitive text the user asked to black out (not too broad)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("redact_call", "query", "pages", "case_sensitive"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="redact_irreversible",
        text="Did the user understand redaction is irreversible in the output?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

PDF_ADD_IMAGE_QUESTIONS = (
    VerificationQuestion(
        id="pdf_input_correct",
        text="Is file_ref or path the target PDF?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "page", "position"),
    ),
    VerificationQuestion(
        id="image_ref_correct",
        text="Is image_file_ref the image the user asked to insert?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("add_image_call", "image_file_ref", "page", "width", "height"), _USER_GOAL),
    ),
)

PDF_ADD_ANNOTATIONS_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF to annotate?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "query", "page", "type"),
    ),
    VerificationQuestion(
        id="annotation_target",
        text="Do query, page, and type match the highlight/underline the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("annotations_call", "query", "page", "type", "color"), _USER_GOAL),
    ),
)

# --- Write: forms ---

PDF_FILL_FORM_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the form PDF the user asked to fill?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "fields", "flatten"),
    ),
    VerificationQuestion(
        id="field_values_match",
        text="Do fields map names→values match what the user asked to enter?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("fill_form_call", "fields"), _USER_GOAL, _PRIOR_FORM_FIELDS),
    ),
    VerificationQuestion(
        id="flatten_intentional",
        text="If flatten=true, did the user want fields locked read-only after fill?",
        severity=SEVERITY_WARN,
        evidence=(_call("fill_form_call", "flatten"), _USER_GOAL),
    ),
)

PDF_FLATTEN_FORM_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the filled form the user asked to flatten?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path"),
    ),
    VerificationQuestion(
        id="flatten_after_fill",
        text="Was fill_form applied first when fields still needed values?",
        severity=SEVERITY_INFO,
        evidence=(_PRIOR_FORM_FIELDS, _USER_GOAL),
    ),
)

PDF_CREATE_FORM_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF to add form fields to?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "fields"),
    ),
    VerificationQuestion(
        id="field_defs_match",
        text="Do field definitions (name, type, page, position) match what the user asked to add?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_form_call", "fields"), _USER_GOAL),
    ),
)

PDF_RESET_FORM_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the form PDF whose values the user asked to clear?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "fields"),
    ),
    VerificationQuestion(
        id="reset_scope",
        text="If fields is set, does it list only the fields to reset; if omitted, was full reset intended?",
        severity=SEVERITY_WARN,
        evidence=(_call("reset_form_call", "fields"), _USER_GOAL),
    ),
)

# --- Write: security ---

PDF_ENCRYPT_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF the user asked to password-protect?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "password", "allow_print"),
    ),
    VerificationQuestion(
        id="permissions_match_intent",
        text="Do allow_print/copy/modify/annotate match restrictions the user requested?",
        severity=SEVERITY_WARN,
        evidence=(_call("encrypt_call", "allow_print", "allow_copy", "allow_modify", "allow_annotate"), _USER_GOAL),
    ),
)

PDF_DECRYPT_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the encrypted PDF the user asked to unlock?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "password"),
    ),
    VerificationQuestion(
        id="password_provided",
        text="Was password supplied for the encrypted PDF?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("decrypt_call", "password"), _USER_GOAL, _PRIOR_PDF_READ),
    ),
)

# --- Write: optimize / metadata / outline / create ---

PDF_OPTIMIZE_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF the user asked to compress?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "level", "linearize"),
    ),
    VerificationQuestion(
        id="level_matches_intent",
        text="Does level match desired tradeoff (aggressive removes images)?",
        severity=SEVERITY_WARN,
        evidence=(_call("optimize_call", "level"), _USER_GOAL),
    ),
)

PDF_REPAIR_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the damaged PDF the user asked to repair?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path"),
    ),
)

PDF_SET_METADATA_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose metadata the user asked to update?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "title", "author", "subject"),
    ),
    VerificationQuestion(
        id="metadata_fields_match",
        text="Do provided title/author/subject/keywords match what the user asked to set?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("set_metadata_call", "title", "author", "subject", "keywords"), _USER_GOAL),
    ),
)

PDF_SET_OUTLINE_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF whose TOC the user asked to replace?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "outline"),
    ),
    VerificationQuestion(
        id="outline_structure_match",
        text="Does outline array match titles, pages, and nesting the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("set_outline_call", "outline"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="replace_not_add",
        text="Did the user want full outline replace, not add_bookmark?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
)

PDF_ADD_BOOKMARK_QUESTIONS = (
    VerificationQuestion(
        id="input_source_correct",
        text="Is file_ref or path the PDF to add a bookmark to?",
        severity=SEVERITY_CRITICAL,
        evidence=_input_evidence("file_ref", "path", "title", "page", "level"),
    ),
    VerificationQuestion(
        id="bookmark_matches",
        text="Do title, page, and level match the bookmark the user asked to add?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("add_bookmark_call", "title", "page", "level"), _USER_GOAL),
    ),
)

PDF_CREATE_QUESTIONS = (
    VerificationQuestion(
        id="content_matches_intent",
        text="Does content reflect what the user asked to put in the new PDF?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_call", "content", "format", "title", "page_size"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="format_matches",
        text="Does format (markdown vs text) match how the content was authored?",
        severity=SEVERITY_WARN,
        evidence=(_call("create_call", "format"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="created_pdf_live",
        text="Does live read_metadata confirm the created PDF exists?",
        severity=SEVERITY_WARN,
        evidence=(_LIVE_PDF_METADATA, _USER_GOAL),
    ),
)

PDF_CREATE_FROM_IMAGES_QUESTIONS = (
    VerificationQuestion(
        id="images_match_intent",
        text="Do image_file_refs include all images the user asked in order?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_images_call", "image_file_refs", "page_size"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="created_pdf_live",
        text="Does live read_metadata confirm the output PDF exists?",
        severity=SEVERITY_WARN,
        evidence=(_LIVE_PDF_METADATA, _USER_GOAL),
    ),
)

PDF_CREATE_BLANK_QUESTIONS = (
    VerificationQuestion(
        id="page_count_matches",
        text="Does pages match how many blank pages the user asked for?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("create_blank_call", "pages", "page_size"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="created_pdf_live",
        text="Does live read_metadata confirm the blank PDF exists?",
        severity=SEVERITY_INFO,
        evidence=(_LIVE_PDF_METADATA, _USER_GOAL),
    ),
)

PDF_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "pdf.extract_text": PDF_EXTRACT_TEXT_QUESTIONS,
    "pdf.extract_tables": PDF_EXTRACT_TABLES_QUESTIONS,
    "pdf.extract_images": PDF_EXTRACT_IMAGES_QUESTIONS,
    "pdf.read_metadata": PDF_READ_METADATA_QUESTIONS,
    "pdf.get_outline": PDF_GET_OUTLINE_QUESTIONS,
    "pdf.search_text": PDF_SEARCH_TEXT_QUESTIONS,
    "pdf.get_page_info": PDF_GET_PAGE_INFO_QUESTIONS,
    "pdf.extract_links": PDF_EXTRACT_LINKS_QUESTIONS,
    "pdf.extract_forms": PDF_EXTRACT_FORMS_QUESTIONS,
    "pdf.ocr": PDF_OCR_QUESTIONS,
    "pdf.is_scanned": PDF_IS_SCANNED_QUESTIONS,
    "pdf.render": PDF_RENDER_QUESTIONS,
    "pdf.get_permissions": PDF_GET_PERMISSIONS_QUESTIONS,
    "pdf.split": PDF_SPLIT_QUESTIONS,
    "pdf.extract_pages": PDF_EXTRACT_PAGES_QUESTIONS,
    "pdf.merge": PDF_MERGE_QUESTIONS,
    "pdf.rotate_pages": PDF_ROTATE_PAGES_QUESTIONS,
    "pdf.delete_pages": PDF_DELETE_PAGES_QUESTIONS,
    "pdf.reorder_pages": PDF_REORDER_PAGES_QUESTIONS,
    "pdf.overlay": PDF_OVERLAY_QUESTIONS,
    "pdf.redact_text": PDF_REDACT_TEXT_QUESTIONS,
    "pdf.add_image": PDF_ADD_IMAGE_QUESTIONS,
    "pdf.add_annotations": PDF_ADD_ANNOTATIONS_QUESTIONS,
    "pdf.fill_form": PDF_FILL_FORM_QUESTIONS,
    "pdf.flatten_form": PDF_FLATTEN_FORM_QUESTIONS,
    "pdf.create_form": PDF_CREATE_FORM_QUESTIONS,
    "pdf.reset_form": PDF_RESET_FORM_QUESTIONS,
    "pdf.encrypt": PDF_ENCRYPT_QUESTIONS,
    "pdf.decrypt": PDF_DECRYPT_QUESTIONS,
    "pdf.optimize": PDF_OPTIMIZE_QUESTIONS,
    "pdf.repair": PDF_REPAIR_QUESTIONS,
    "pdf.set_metadata": PDF_SET_METADATA_QUESTIONS,
    "pdf.set_outline": PDF_SET_OUTLINE_QUESTIONS,
    "pdf.add_bookmark": PDF_ADD_BOOKMARK_QUESTIONS,
    "pdf.create": PDF_CREATE_QUESTIONS,
    "pdf.create_from_images": PDF_CREATE_FROM_IMAGES_QUESTIONS,
    "pdf.create_blank": PDF_CREATE_BLANK_QUESTIONS,
}

PDF_CHECKER_ALL_TOOL_NAMES = tuple(PDF_CHECKER_QUESTIONS_BY_TOOL.keys())

PDF_CHECKER_READ_TOOL_NAMES = tuple(
    name
    for name in PDF_CHECKER_ALL_TOOL_NAMES
    if name.endswith(
        (
            ".extract_text",
            ".extract_tables",
            ".extract_images",
            ".read_metadata",
            ".get_outline",
            ".search_text",
            ".get_page_info",
            ".extract_links",
            ".extract_forms",
            ".ocr",
            ".is_scanned",
            ".render",
            ".get_permissions",
        )
    )
)

PDF_CHECKER_WRITE_TOOL_NAMES = tuple(
    name for name in PDF_CHECKER_ALL_TOOL_NAMES if name not in PDF_CHECKER_READ_TOOL_NAMES
)
