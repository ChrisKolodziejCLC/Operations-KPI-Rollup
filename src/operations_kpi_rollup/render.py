import json
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .charts import generate_charts
from .context import prepare_context


def _environment() -> Environment:
    template_dir = Path(__file__).parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _plain_text(context: Dict[str, Any]) -> str:
    lines = [
        "Operations KPI Rollup",
        f"Report date: {context['report_date']}",
        f"Scope: {context['scope']['label']}",
        "",
    ]
    for card in context["cards"]:
        lines.append(f"{card['label']}: {card['value']} ({card['detail']})")
    if context["data_quality_notes"]:
        lines.extend(["", "Data quality notes:"])
        lines.extend(f"- {note}" for note in context["data_quality_notes"])
    lines.append("")
    lines.append("This preview was generated from an immutable JSON snapshot. It was not sent automatically.")
    return "\n".join(lines)


def _render_html(context: Dict[str, Any], charts: Dict[str, Dict[str, str]], email_mode: bool) -> str:
    rendered_charts: Dict[str, Dict[str, str]] = {}
    for key, chart in charts.items():
        rendered_charts[key] = dict(chart)
        rendered_charts[key]["src"] = f"cid:{chart['cid']}" if email_mode else chart["filename"]
    return _environment().get_template("report.html.j2").render(**context, charts=rendered_charts)


def _build_preview_eml(context: Dict[str, Any], html: str, charts: Dict[str, Dict[str, str]], output_dir: Path) -> Path:
    message = EmailMessage()
    message["Subject"] = f"[PREVIEW — DO NOT SEND] Operations KPI Rollup — {context['report_date']}"
    message["From"] = "operations-kpi-preview@invalid.example"
    message["To"] = "undisclosed-recipients:;"
    message["X-Operations-KPI-Preview"] = "true"
    message.set_content(_plain_text(context))
    message.add_alternative(html, subtype="html")
    html_part = message.get_payload()[-1]
    for chart in charts.values():
        image_path = output_dir / chart["filename"]
        html_part.add_related(
            image_path.read_bytes(),
            maintype="image",
            subtype="png",
            cid=f"<{chart['cid']}>",
            filename=chart["filename"],
            disposition="inline",
        )
    eml_path = output_dir / "report-preview.eml"
    eml_path.write_bytes(message.as_bytes())
    return eml_path


def build_report(snapshot: Dict[str, Any], output_dir: Path) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    context = prepare_context(snapshot)
    charts = generate_charts(context, output_dir)

    preview_html = _render_html(context, charts, email_mode=False)
    email_html = _render_html(context, charts, email_mode=True)

    html_path = output_dir / "report.html"
    html_path.write_text(preview_html, encoding="utf-8")
    snapshot_path = output_dir / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    eml_path = _build_preview_eml(context, email_html, charts, output_dir)

    return {"html": html_path, "eml_preview": eml_path, "snapshot": snapshot_path}
