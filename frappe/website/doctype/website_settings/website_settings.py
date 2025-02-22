# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE
from typing import Dict, List
from urllib.parse import quote

import frappe
from frappe import _
from frappe.integrations.doctype.google_settings.google_settings import get_auth_url
from frappe.model.document import Document
from frappe.utils import encode, get_request_site_address

INDEXING_SCOPES = "https://www.googleapis.com/auth/indexing"


class WebsiteSettings(Document):
	def validate(self):
		self.validate_top_bar_items()
		self.validate_footer_items()
		self.validate_home_page()
		self.validate_google_settings()

	def validate_home_page(self):
		if frappe.flags.in_install:
			return
		from frappe.website.path_resolver import PathResolver

		if self.home_page and not PathResolver(self.home_page).is_valid_path():
			frappe.msgprint(
				_("Invalid Home Page") + " (Standard pages - home, login, products, blog, about, contact)"
			)
			self.home_page = ""

	def validate_top_bar_items(self):
		"""validate url in top bar items"""
		for top_bar_item in self.get("top_bar_items"):
			if top_bar_item.parent_label:
				parent_label_item = self.get("top_bar_items", {"label": top_bar_item.parent_label})

				if not parent_label_item:
					# invalid item
					frappe.throw(
						_("{0} does not exist in row {1}").format(top_bar_item.parent_label, top_bar_item.idx)
					)

				elif not parent_label_item[0] or parent_label_item[0].url:
					# parent cannot have url
					frappe.throw(
						_("{0} in row {1} cannot have both URL and child items").format(
							top_bar_item.parent_label, top_bar_item.idx
						)
					)

	def validate_footer_items(self):
		"""validate url in top bar items"""
		for footer_item in self.get("footer_items"):
			if footer_item.parent_label:
				parent_label_item = self.get("footer_items", {"label": footer_item.parent_label})

				if not parent_label_item:
					# invalid item
					frappe.throw(
						_("{0} does not exist in row {1}").format(footer_item.parent_label, footer_item.idx)
					)

				elif not parent_label_item[0] or parent_label_item[0].url:
					# parent cannot have url
					frappe.throw(
						_("{0} in row {1} cannot have both URL and child items").format(
							footer_item.parent_label, footer_item.idx
						)
					)

	def validate_google_settings(self):
		if self.enable_google_indexing and not frappe.db.get_single_value("Google Settings", "enable"):
			frappe.throw(_("Enable Google API in Google Settings."))

	def on_update(self):
		self.clear_cache()

	def clear_cache(self):
		# make js and css
		# clear web cache (for menus!)
		frappe.clear_cache(user="Guest")

		from frappe.website.utils import clear_cache

		clear_cache()

		# clears role based home pages
		frappe.clear_cache()

	def get_access_token(self):
		import requests

		google_settings = frappe.get_doc("Google Settings")

		if not google_settings.enable:
			frappe.throw(_("Google Integration is disabled."))

		if not self.indexing_refresh_token:
			button_label = frappe.bold(_("Allow API Indexing Access"))
			raise frappe.ValidationError(_("Click on {0} to generate Refresh Token.").format(button_label))

		data = {
			"client_id": google_settings.client_id,
			"client_secret": google_settings.get_password(fieldname="client_secret", raise_exception=False),
			"refresh_token": self.get_password(fieldname="indexing_refresh_token", raise_exception=False),
			"grant_type": "refresh_token",
			"scope": INDEXING_SCOPES,
		}

		try:
			res = requests.post(get_auth_url(), data=data).json()
		except requests.exceptions.HTTPError:
			button_label = frappe.bold(_("Allow Google Indexing Access"))
			frappe.throw(
				_(
					"Something went wrong during the token generation. Click on {0} to generate a new one."
				).format(button_label)
			)

		return res.get("access_token")


def get_website_settings(context=None):
	hooks = frappe.get_hooks()
	context = frappe._dict(context or {})
	settings: "WebsiteSettings" = frappe.get_single("Website Settings")

	context = context.update(
		{
			"top_bar_items": get_items("top_bar_items"),
			"footer_items": get_items("footer_items"),
			"post_login": [
				{"label": _("My Account"), "url": "/me"},
				{"label": _("Log out"), "url": "/?cmd=web_logout"},
			],
		}
	)

	for k in [
		"banner_html",
		"banner_image",
		"brand_html",
		"copyright",
		"twitter_share_via",
		"facebook_share",
		"google_plus_one",
		"twitter_share",
		"linked_in_share",
		"disable_signup",
		"hide_footer_signup",
		"head_html",
		"title_prefix",
		"navbar_template",
		"footer_template",
		"navbar_search",
		"enable_view_tracking",
		"footer_logo",
		"call_to_action",
		"call_to_action_url",
		"show_language_picker",
		"footer_powered",
	]:
		if setting_value := settings.get(k):
			context[k] = setting_value

	for k in [
		"facebook_share",
		"google_plus_one",
		"twitter_share",
		"linked_in_share",
		"disable_signup",
	]:
		context[k] = int(context.get(k) or 0)

	if settings.address:
		context["footer_address"] = settings.address

	if frappe.request:
		context.url = quote(str(get_request_site_address(full_address=True)), safe="/:")

	context.encoded_title = quote(encode(context.title or ""), str(""))

	context.web_include_js = hooks.web_include_js or []

	context.web_include_css = hooks.web_include_css or []

	via_hooks = hooks.website_context or []
	for key in via_hooks:
		context[key] = via_hooks[key]
		if key not in ("top_bar_items", "footer_items", "post_login") and isinstance(
			context[key], (list, tuple)
		):
			context[key] = context[key][-1]

	if context.disable_website_theme:
		context.theme = frappe._dict()

	else:
		from frappe.website.doctype.website_theme.website_theme import get_active_theme

		context.theme = get_active_theme() or frappe._dict()

	if not context.get("favicon"):
		context["favicon"] = "/assets/frappe/images/frappe-favicon.svg"

	if settings.favicon and settings.favicon != "attach_files:":
		context["favicon"] = settings.favicon

	context["hide_login"] = settings.hide_login

	if settings.splash_image:
		context["splash_image"] = settings.splash_image

	return context


def get_items(parentfield: str) -> List[Dict]:
	_items = frappe.get_all(
		"Top Bar Item",
		filters={"parent": "Website Settings", "parentfield": parentfield},
		order_by="idx asc",
		fields="*",
	)
	top_items = _items.copy()

	# attach child items to top bar
	for item in _items:
		if not item["parent_label"]:
			continue

		for top_bar_item in top_items:
			if top_bar_item["label"] != item["parent_label"]:
				continue

			if "child_items" not in top_bar_item:
				top_bar_item["child_items"] = []

			top_bar_item["child_items"].append(item)

			break

	return top_items


@frappe.whitelist(allow_guest=True)
def get_auto_account_deletion():
	return frappe.db.get_single_value("Website Settings", "auto_account_deletion")
