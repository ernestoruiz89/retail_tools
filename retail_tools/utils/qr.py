# Copyright (c) 2026, Ernesto Ruiz and contributors
# For license information, please see license.txt

from __future__ import annotations

import base64
from io import BytesIO
from urllib.parse import urlparse


def normalize_qr_url(raw_url: str | None) -> str:
	"""Normalize and validate a web or social media URL for QR printing."""
	value = (raw_url or "").strip()
	if not value:
		return ""

	if "://" not in value:
		value = f"https://{value}"

	parsed = urlparse(value)
	if parsed.scheme not in ("http", "https") or not parsed.netloc or "." not in parsed.netloc:
		raise ValueError("Ingrese una URL válida (ej. https://www.tutienda.com o https://www.instagram.com/tu_tienda/).")

	return value


def get_qr_data_uri(content: str | None, scale: int = 4) -> str:
	"""Generate a base64 SVG data URI QR code for use in Print Formats."""
	text = (content or "").strip()
	if not text:
		return ""

	# Primary: pyqrcode (bundled with Frappe Framework)
	try:
		import pyqrcode

		qr = pyqrcode.create(text, error="M")
		buf = BytesIO()
		qr.svg(buf, scale=scale, quiet_zone=2, xmldecl=False, omithw=False)
		encoded = base64.b64encode(buf.getvalue()).decode("ascii")
		return f"data:image/svg+xml;base64,{encoded}"
	except ImportError:
		pass

	# Secondary: python-qrcode
	try:
		import qrcode
		from qrcode.image.svg import SvgPathImage

		img = qrcode.make(text, image_factory=SvgPathImage, box_size=max(scale * 2, 6), border=2)
		buf = BytesIO()
		img.save(buf)
		encoded = base64.b64encode(buf.getvalue()).decode("ascii")
		return f"data:image/svg+xml;base64,{encoded}"
	except ImportError:
		return ""


def get_pos_qr_context() -> dict[str, str]:
	"""Return QR configuration from Retail Tools Settings for Jinja print formats."""
	settings: dict[str, str] = {}
	try:
		import frappe

		if frappe.db.exists("DocType", "Retail Tools Settings"):
			settings = frappe.db.get_singles_dict("Retail Tools Settings") or {}
	except Exception:
		settings = {}

	qr_url = (settings.get("qr_url") or "").strip()
	qr_subtitle = (settings.get("qr_subtitle") or "").strip()
	qr_label = (settings.get("qr_label") or "").strip()
	pos_footer_message = (settings.get("pos_footer_message") or "").strip()

	return {
		"qr_url": qr_url,
		"qr_subtitle": qr_subtitle,
		"qr_label": qr_label,
		"pos_footer_message": pos_footer_message,
		"qr_data_uri": get_qr_data_uri(qr_url) if qr_url else "",
	}
