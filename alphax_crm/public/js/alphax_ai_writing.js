// AlphaX AI writing tools on CRM forms:
//  * an "AI" button on text fields: Check spelling, Translate to Arabic / English,
//    Improve wording, Make formal, Shorten (preview first, nothing changes until Replace)
//  * Arabic + English spell check when the user leaves a field (Suggest or Auto-correct)
// Config arrives in frappe.boot.alphax_ai_writing (alphax_crm.ai.writing.boot_session).
// Pure helpers live in alphax_ai_writing_lib so they can be tested outside the browser.

(function (root) {
	const WORD = "[\\p{L}\\p{N}\\p{M}]";
	const TAG_SPLIT = /(<[^>]*>|&[a-zA-Z#0-9]+;)/;

	function escape_regex(s) {
		return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	}
	// Same rules as alphax_crm.ai.pure.apply_changes on the server.
	function apply_changes(text, changes, is_html) {
		if (!changes || !changes.length) return text;
		const parts = is_html ? String(text).split(TAG_SPLIT) : [String(text)];
		for (let i = 0; i < parts.length; i++) {
			if (is_html && i % 2 === 1) continue;
			for (const c of changes) {
				const re = new RegExp(`(?<!${WORD})${escape_regex(c.original)}(?!${WORD})`, "gu");
				parts[i] = parts[i].replace(re, () => c.corrected);
			}
		}
		return parts.join("");
	}
	// addresses, contact details and technical fields are never checked or rewritten
	const EXCLUDED = ["address", "email", "phone", "mobile", "whatsapp", "url", "website", "iban", "code",
		"json", "html", "script", "query", "template", "formula", "condition", "token", "password"];
	function is_eligible_field(df, cfg) {
		if (!df || df.read_only || df.hidden || df.is_virtual) return false;
		const fname = (df.fieldname || "").toLowerCase();
		if (EXCLUDED.concat(cfg.excluded_field_patterns || []).some((p) => fname.includes(p))) return false;
		if (["Small Text", "Text", "Long Text", "Text Editor"].includes(df.fieldtype)) return true;
		if (df.fieldtype === "Data") {
			if (["Email", "Phone", "URL", "Barcode", "IBAN", "Name"].includes(df.options)) return false;
			const name = (df.fieldname || "").toLowerCase();
			return (cfg.data_field_patterns || []).some((p) => name.includes(p));
		}
		return false;
	}
	root.alphax_ai_writing_lib = { apply_changes, is_eligible_field };
})(typeof window !== "undefined" ? window : globalThis);

(function () {
	if (typeof frappe === "undefined" || typeof $ === "undefined") return;
	const lib = window.alphax_ai_writing_lib;
	const last_checked = {};
	const timers = {};
	let box = null;

	const cfg = () => (frappe.boot && frappe.boot.alphax_ai_writing) || null;
	// frappe.xcall may return a jQuery-style thenable: normalise to a real Promise (finally/catch)
	const xcall = (method, args) => Promise.resolve(frappe.xcall(method, args));
	// If the NeotecAI Intake app's site-wide spell check is on, let it handle typing checks.
	const other_spellcheck = () => !!(frappe.boot && frappe.boot.neotecai_spellcheck && frappe.boot.neotecai_spellcheck.enabled);

	function inject_style() {
		if (document.getElementById("alphax-ai-writing-style")) return;
		$("<style id='alphax-ai-writing-style'>").text(`
		.ax-ai-btn{border:1px solid var(--border-color,#d1d8dd);background:var(--card-bg,#fff);color:var(--text-muted,#687178);
			border-radius:999px;font-size:11px;line-height:1;padding:3px 8px;margin-inline-start:6px;cursor:pointer;vertical-align:middle}
		.ax-ai-btn:hover,.ax-ai-btn:focus-visible{color:var(--text-color,#1f272e);border-color:var(--gray-500,#98a1a9)}
		.ax-ai-pop{position:absolute;z-index:1050;max-width:min(560px,92vw);background:var(--card-bg,#fff);
			border:1px solid var(--border-color,#d1d8dd);border-radius:10px;box-shadow:var(--shadow-lg,0 6px 24px rgba(0,0,0,.15));
			padding:10px 12px;font-size:13px;color:var(--text-color,#1f272e)}
		.ax-ai-pop .ax-title{font-weight:600;margin-bottom:6px}
		.ax-ai-pop .ax-chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
		.ax-ai-pop .ax-chip{display:inline-flex;align-items:center;gap:6px;background:var(--control-bg,#f4f5f6);border-radius:999px;padding:3px 6px 3px 10px}
		.ax-ai-pop .ax-chip.ax-off{opacity:.45;text-decoration:line-through}
		.ax-ai-pop .ax-old{color:var(--red-600,#c0392b);text-decoration:line-through}
		.ax-ai-pop .ax-new{color:var(--green-700,#1e7e34);font-weight:600}
		.ax-ai-pop .ax-x,.ax-ai-pop .ax-dict{cursor:pointer;border:0;background:none;padding:0 4px;font-size:15px;line-height:1;color:var(--text-muted,#687178)}
		.ax-ai-pop .ax-actions{display:flex;gap:6px;justify-content:flex-end}
		.ax-ai-menu{position:absolute;z-index:1050;background:var(--card-bg,#fff);border:1px solid var(--border-color,#d1d8dd);
			border-radius:8px;box-shadow:var(--shadow-lg,0 6px 24px rgba(0,0,0,.15));padding:4px;min-width:210px}
		.ax-ai-menu button{display:block;width:100%;text-align:start;border:0;background:none;padding:7px 10px;border-radius:6px;font-size:13px;color:var(--text-color,#1f272e)}
		.ax-ai-menu button:hover,.ax-ai-menu button:focus-visible{background:var(--control-bg,#f4f5f6)}
		.ax-ai-compare{display:grid;grid-template-columns:1fr 1fr;gap:12px}
		@media (max-width:640px){.ax-ai-compare{grid-template-columns:1fr}}
		.ax-ai-compare .ax-pane{border:1px solid var(--border-color,#d1d8dd);border-radius:8px;padding:10px;max-height:45vh;overflow:auto;white-space:pre-wrap;unicode-bidi:plaintext}
		.ax-ai-compare .ax-label{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted,#687178);margin-bottom:4px}
		.ax-ai-warn{color:var(--orange-700,#b45309);margin-top:8px}`).appendTo("head");
	}

	// ------------------------------------------------------------------ context
	function context_for(el) {
		const c = cfg();
		const frm = window.cur_frm;
		if (!c || !frm || !frm.doc || $(el).closest(".modal").length) return null;
		const $control = $(el).closest(".frappe-control[data-fieldname]");
		if (!$control.length) return null;
		const fieldname = $control.attr("data-fieldname");
		let doctype = frm.doctype;
		let docname = frm.docname;
		const $row = $(el).closest(".grid-row[data-name]");
		if ($row.length) {
			const rowname = $row.attr("data-name");
			let found = null;
			for (const key of Object.keys(frm.doc)) {
				if (Array.isArray(frm.doc[key])) {
					found = frm.doc[key].find((r) => r && r.name === rowname);
					if (found) break;
				}
			}
			if (!found) return null;
			doctype = found.doctype;
			docname = found.name;
		}
		if (!(c.doctypes || []).includes(frm.doctype)) return null;
		const doc = locals[doctype] && locals[doctype][docname];
		const df = frappe.meta.get_docfield(doctype, fieldname, docname);
		if (!doc || !lib.is_eligible_field(df, c)) return null;
		if (frm.doc.docstatus > 0 && !df.allow_on_submit) return null;
		return { frm, doctype, docname, fieldname, df, $control, key: `${doctype}|${docname}|${fieldname}`,
			is_html: df.fieldtype === "Text Editor" ? 1 : 0 };
	}
	const value_of = (ctx) => (locals[ctx.doctype][ctx.docname] || {})[ctx.fieldname];
	function set_text(ctx, value) {
		last_checked[ctx.key] = value;
		frappe.model.set_value(ctx.doctype, ctx.docname, ctx.fieldname, value);
	}
	function api_args(ctx, text) {
		return { text, is_html: ctx.is_html, doctype: ctx.frm.doctype, docname: ctx.frm.is_new() ? null : ctx.frm.docname };
	}

	// ------------------------------------------------------------------ AI button + menu
	function add_button(ctx) {
		const $label = ctx.$control.find(".control-label").first();
		if (!$label.length || ctx.$control.find(".ax-ai-btn").length) return;
		const $btn = $(`<button type="button" class="ax-ai-btn" title="${__("AI writing tools")}" aria-haspopup="menu">✦ ${__("AI")}</button>`);
		$btn.on("mousedown", (e) => e.preventDefault()).on("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			const fresh = context_for(ctx.$control.find("input, textarea, .ql-editor").get(0) || ctx.$control.get(0)) || ctx;
			open_menu(fresh, $btn);
		});
		$label.after($btn);
	}

	function open_menu(ctx, $anchor) {
		inject_style();
		close_all();
		const items = [
			["spell", __("Check spelling")],
			["translate:Arabic", __("Translate to Arabic") + " (العربية)"],
			["translate:English", __("Translate to English")],
			["improve", __("Improve wording")],
			["formal", __("Make more formal")],
			["shorten", __("Shorten")],
		];
		box = $(`<div class="ax-ai-menu" role="menu"></div>`);
		items.forEach(([key, label]) => {
			$(`<button type="button" role="menuitem"></button>`).text(label).on("click", () => {
				close_all();
				run_action(ctx, key);
			}).appendTo(box);
		});
		place(box, $anchor[0]);
		$("body").append(box);
		box.find("button").first().trigger("focus");
	}

	function run_action(ctx, key) {
		const text = value_of(ctx);
		const plain = ctx.is_html ? $("<div>").html(text || "").text() : text || "";
		if (!plain.trim()) {
			frappe.show_alert({ message: __("The field is empty."), indicator: "orange" });
			return;
		}
		if (key === "spell") {
			frappe.dom.freeze(__("Checking spelling…"));
			xcall("alphax_crm.ai.writing.spell_check", api_args(ctx, text))
				.then((r) => {
					if (!r || !r.changes || !r.changes.length) {
						frappe.show_alert({ message: __("No spelling mistakes found."), indicator: "green" });
						return;
					}
					show_spell_box(ctx, text, r.changes);
				})
				.finally(() => frappe.dom.unfreeze());
			return;
		}
		const [action, target] = key.split(":");
		frappe.dom.freeze(action === "translate" ? __("Translating…") : __("Rewriting…"));
		xcall("alphax_crm.ai.writing.transform", { ...api_args(ctx, text), action, target_language: target || null })
			.then((r) => show_result_dialog(ctx, text, action, r))
			.finally(() => frappe.dom.unfreeze());
	}

	function show_result_dialog(ctx, original, action, r) {
		const titles = { translate: __("Translation ({0})", [__(r.target_language)]), improve: __("Improved wording"),
			formal: __("More formal"), shorten: __("Shorter version") };
		const as_text = (v) => (ctx.is_html ? $("<div>").html(v || "").text() : v || "");
		const d = new frappe.ui.Dialog({
			title: titles[action] || __("AI result"),
			size: "large",
			fields: [{ fieldname: "body", fieldtype: "HTML" }],
			primary_action_label: __("Replace"),
			primary_action() {
				if (value_of(ctx) !== original) {
					frappe.msgprint(__("The field changed while the AI was working. Copy the result instead."));
					return;
				}
				set_text(ctx, r.result);
				d.hide();
				frappe.show_alert({ message: __("{0} updated", [__(ctx.df.label || ctx.fieldname)]), indicator: "green" });
			},
			secondary_action_label: action === "translate" ? __("Add Below Original") : __("Copy"),
			secondary_action() {
				if (action === "translate") {
					if (value_of(ctx) !== original) return;
					const joined = ctx.is_html ? `${original}<p><br></p>${r.result}` : `${original}\n\n${r.result}`;
					set_text(ctx, joined);
					d.hide();
				} else {
					frappe.utils.copy_to_clipboard(as_text(r.result));
				}
			},
		});
		const warn = (r.warnings || []).map((w) => `<div class="ax-ai-warn">⚠ ${frappe.utils.escape_html(w)}</div>`).join("");
		d.fields_dict.body.$wrapper.html(`<div class="ax-ai-compare">
			<div><div class="ax-label">${__("Original")}</div><div class="ax-pane" dir="auto"></div></div>
			<div><div class="ax-label">${__("Result")}</div><div class="ax-pane ax-result" dir="auto"></div></div>
			</div>${warn}`);
		const $panes = d.fields_dict.body.$wrapper.find(".ax-pane");
		$panes.eq(0).text(as_text(original));
		$panes.eq(1).text(as_text(r.result));
		d.show();
	}

	// ------------------------------------------------------------------ spell check on blur
	function schedule_check(el) {
		const c = cfg();
		if (!c || c.spell_mode === "Off" || other_spellcheck()) return;
		const ctx = context_for(el);
		if (!ctx) return;
		clearTimeout(timers[ctx.key]);
		timers[ctx.key] = setTimeout(() => run_check(ctx, c), 600);
	}

	function run_check(ctx, c) {
		const text = value_of(ctx);
		if (!text || typeof text !== "string") return;
		const plain = ctx.is_html ? $("<div>").html(text).text() : text;
		if (plain.trim().length < (c.min_chars || 4) || last_checked[ctx.key] === text) return;
		last_checked[ctx.key] = text;
		xcall("alphax_crm.ai.writing.spell_check", api_args(ctx, text))
			.then((r) => {
				if (!r || !r.changes || !r.changes.length || value_of(ctx) !== text) return;
				if (c.spell_mode === "Auto-correct") auto_correct(ctx, text, r.changes);
				else show_spell_box(ctx, text, r.changes);
			})
			.catch(() => delete last_checked[ctx.key]);
	}

	const describe = (changes) =>
		changes.map((ch) => `${frappe.utils.escape_html(ch.original)} → ${frappe.utils.escape_html(ch.corrected)}`).join(", ");

	function auto_correct(ctx, text, changes) {
		set_text(ctx, lib.apply_changes(text, changes, ctx.is_html));
		const id = "ax-undo-" + Math.random().toString(36).slice(2);
		frappe.show_alert({ message: `${__("Spelling corrected")} (${__(ctx.df.label || ctx.fieldname)}): ${describe(changes)}
			&nbsp;<a id="${id}" href="#">${__("Undo")}</a>`, indicator: "blue" }, 8);
		setTimeout(() => $(`#${id}`).on("click", (e) => {
			e.preventDefault();
			set_text(ctx, text);
			frappe.show_alert({ message: __("Spelling correction undone"), indicator: "gray" }, 3);
		}), 50);
	}

	function show_spell_box(ctx, text, changes) {
		inject_style();
		close_all();
		const state = changes.map(() => true);
		box = $(`<div class="ax-ai-pop" role="dialog" aria-label="${__("Spelling suggestions")}">
			<div class="ax-title">✦ ${__("Spelling")}: ${frappe.utils.escape_html(__(ctx.df.label || ctx.fieldname))}</div>
			<div class="ax-chips"></div>
			<div class="ax-actions">
				<button type="button" class="btn btn-xs btn-default ax-ignore">${__("Ignore")}</button>
				<button type="button" class="btn btn-xs btn-primary ax-apply">${__("Apply")}</button>
			</div></div>`);
		changes.forEach((ch, i) => {
			const chip = $(`<span class="ax-chip" dir="auto"><span class="ax-old" dir="auto"></span><span>→</span>
				<span class="ax-new" dir="auto"></span>
				<button type="button" class="ax-dict" title="${__("My spelling is correct: add to AlphaX AI Terms")}" aria-label="${__("Add to dictionary")}">+</button>
				<button type="button" class="ax-x" title="${__("Keep my spelling this time")}" aria-label="${__("Keep my spelling")}">×</button></span>`);
			chip.find(".ax-old").text(ch.original);
			chip.find(".ax-new").text(ch.corrected);
			chip.find(".ax-x").on("click", () => {
				state[i] = !state[i];
				chip.toggleClass("ax-off", !state[i]);
			});
			chip.find(".ax-dict").on("click", () => {
				xcall("alphax_crm.ai.writing.add_term", { word: ch.original }).then(() =>
					frappe.show_alert({ message: __("{0} added to AlphaX AI Terms", [frappe.utils.escape_html(ch.original)]), indicator: "green" }, 3));
				state[i] = false;
				chip.addClass("ax-off");
			});
			box.find(".ax-chips").append(chip);
		});
		box.find(".ax-ignore").on("click", close_all);
		box.find(".ax-apply").on("click", () => {
			const chosen = changes.filter((_, i) => state[i]);
			if (chosen.length && value_of(ctx) === text) set_text(ctx, lib.apply_changes(text, chosen, ctx.is_html));
			close_all();
		});
		const target = ctx.$control.find(".control-input, .ql-container").first();
		place(box, (target.length ? target : ctx.$control)[0], true);
		$("body").append(box);
	}

	function place($el, anchor, below_wide) {
		const rect = anchor.getBoundingClientRect();
		const width = below_wide ? Math.min(560, window.innerWidth * 0.92) : 230;
		let left = rect.left + window.scrollX;
		if (left + width > window.innerWidth - 8) left = Math.max(8, window.innerWidth - width - 8);
		$el.css({ top: rect.bottom + window.scrollY + 6, left });
	}

	function close_all() {
		if (box) box.remove();
		box = null;
	}

	// ------------------------------------------------------------------ wiring
	function decorate_form(frm) {
		const c = cfg();
		if (!c || !frm || !(c.doctypes || []).includes(frm.doctype)) return;
		inject_style();
		Object.values(frm.fields_dict || {}).forEach((field) => {
			if (!field.$wrapper || !lib.is_eligible_field(field.df, c)) return;
			const ctx = context_for(field.$wrapper.find(".control-label").get(0) || field.$wrapper.get(0));
			if (ctx) add_button(ctx);
		});
	}
	$(document).on("form-refresh", (e, frm) => setTimeout(() => decorate_form(frm), 300));
	$(document).on("focusin", ".frappe-control input, .frappe-control textarea, .frappe-control .ql-editor", function () {
		if (!cfg()) return;
		const ctx = context_for(this);
		if (ctx) {
			inject_style();
			add_button(ctx); // child-table row forms are created lazily
			if (this.tagName === "TEXTAREA" || this.classList.contains("ql-editor")) this.setAttribute("spellcheck", "true");
		}
	});
	$(document).on("focusout", ".frappe-control input, .frappe-control textarea, .frappe-control .ql-editor", function () {
		if (cfg()) schedule_check(this);
	});
	$(document).on("click", (e) => {
		if (box && !$(e.target).closest(".ax-ai-pop, .ax-ai-menu, .ax-ai-btn").length) close_all();
	});
	$(document).on("keydown", (e) => {
		if (e.key === "Escape") close_all();
	});
	if (frappe.router && frappe.router.on) frappe.router.on("change", close_all);
})();
