import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

from operations_kpi_rollup.render import build_report


FIXTURE = Path(__file__).parents[1] / "examples" / "2026-09-16.json"


def test_build_creates_safe_reproducible_preview(tmp_path):
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    outputs = build_report(snapshot, tmp_path)

    html = outputs["html"].read_text(encoding="utf-8")
    saved_snapshot = json.loads(outputs["snapshot"].read_text(encoding="utf-8"))
    message = BytesParser(policy=policy.default).parsebytes(outputs["eml_preview"].read_bytes())

    assert saved_snapshot == snapshot
    assert "Paint plan composite" in html
    assert ">Paint OEE" not in html
    assert "301.0" in html
    assert message["X-Operations-KPI-Preview"] == "true"
    assert message["Subject"].startswith("[PREVIEW — DO NOT SEND]")
    assert message["From"] == "operations-kpi-preview@invalid.example"
    inline_images = [part for part in message.walk() if part.get_content_type() == "image/png"]
    assert len(inline_images) == 4
    assert all(part.get_content_disposition() == "inline" for part in inline_images)
    assert all(part["Content-ID"] for part in inline_images)

    generated_pngs = {path.name for path in tmp_path.glob("*.png")}
    assert generated_pngs == {
        "daily-throughput.png",
        "daily-yield.png",
        "painter-throughput.png",
        "shipping-by-line-set.png",
    }
    assert "monthly" not in " ".join(generated_pngs)
    assert "repaint" not in " ".join(generated_pngs)
