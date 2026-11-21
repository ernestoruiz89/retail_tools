# Copyright (c) 2026, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from retail_tools.utils.qr import normalize_qr_url


class RetailToolsSettings(Document):
	def validate(self):
		if self.qr_url:
			try:
				self.qr_url = normalize_qr_url(self.qr_url)
			except ValueError as exc:
				frappe.throw(_(str(exc)))
		if self.qr_subtitle:
			self.qr_subtitle = self.qr_subtitle.strip()
		if self.qr_label:
			self.qr_label = self.qr_label.strip()
