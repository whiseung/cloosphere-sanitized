<script lang="ts">
	import { basicSetup, EditorView } from 'codemirror';
	import { keymap, placeholder } from '@codemirror/view';
	import { Annotation, Compartment, EditorState, Prec } from '@codemirror/state';

	import { acceptCompletion, autocompletion } from '@codemirror/autocomplete';
	import { indentWithTab } from '@codemirror/commands';

	import {
		HighlightStyle,
		indentUnit,
		LanguageDescription,
		syntaxHighlighting
	} from '@codemirror/language';
	import { languages } from '@codemirror/language-data';
	import { tags as t } from '@lezer/highlight';

	import { oneDark } from '@codemirror/theme-one-dark';

	// Light-mode palette. Dark mode is overridden by `oneDark` via the theme
	// compartment, so this stays inactive there.
	const cloosphereLightHighlight = HighlightStyle.define([
		{
			tag: [t.keyword, t.bool, t.null, t.modifier, t.controlKeyword, t.operatorKeyword],
			color: '#155dfc',
			fontWeight: '600'
		},
		{
			tag: [t.function(t.variableName), t.function(t.propertyName), t.standard(t.variableName)],
			color: '#00627a'
		},
		{ tag: [t.string, t.special(t.string)], color: '#1e7c3a' },
		{ tag: [t.number, t.integer, t.float], color: '#af6500' },
		{ tag: [t.comment, t.lineComment, t.blockComment, t.docComment], color: '#8c8c8c', fontStyle: 'italic' },
		{ tag: [t.operator, t.compareOperator, t.logicOperator, t.arithmeticOperator], color: '#6a4d8c' },
		{ tag: [t.punctuation, t.separator, t.bracket, t.paren, t.brace, t.squareBracket], color: '#5f6066' },
		{ tag: [t.variableName, t.propertyName], color: '#1a1a1a' },
		{ tag: [t.typeName, t.className, t.namespace], color: '#7c4dff', fontWeight: '500' },
		{ tag: [t.tagName, t.attributeName], color: '#cb2755' },
		{ tag: t.invalid, color: '#d92d20' }
	]);

	import { onMount, createEventDispatcher, getContext, tick } from 'svelte';

	import { formatPythonCode } from '$lib/apis/utils';
	import { toast } from 'svelte-sonner';

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	export let boilerplate = '';
	export let value = '';

	export let onSave: () => void = () => {};
	export let onChange: (value: string) => void = () => {};
	/** Fired on Cmd/Ctrl+Enter. */
	export let onRun: () => void = () => {};

	let _value = '';

	// Marks programmatic value-sync transactions so the read-only transaction
	// filter can allow them while blocking user edits.
	const syncAnnotation = Annotation.define();

	// `!== undefined` so empty strings (cleared tab) still sync.
	$: if (value !== undefined) {
		updateValue();
	}

	const updateValue = () => {
		if (_value === value) return;
		_value = value;
		if (!codeEditor) return;
		const cur = codeEditor.state.doc.toString();
		if (cur === value) return;
		codeEditor.dispatch({
			changes: { from: 0, to: codeEditor.state.doc.length, insert: value ?? '' },
			annotations: syncAnnotation.of(true)
		});
	};

	export let id = '';
	export let lang = '';
	export let dialect:
		| ''
		| 'postgresql'
		| 'mysql'
		| 'mariadb'
		| 'mssql'
		| 'sqlite'
		| 'plsql'
		| 'cassandra'
		| 'standard' = '';
	/** Schema for SQL autocomplete — `{ table_name: [column1, ...] }`.
	 * When supplied, `Ctrl+Space` after `FROM ` suggests real table names,
	 * and `table.` suggests the table's columns. Re-applied whenever the
	 * reference changes (e.g. user re-extracts schema). */
	export let schema: Record<string, string[]> | null = null;
	/** When true, the editor renders but cannot be edited. Useful for
	 * showing formatted SQL with syntax highlighting + line numbers in
	 * read-only contexts (e.g. memory detail modal view mode). */
	export let readOnly: boolean = false;

	let codeEditor;

	export const focus = () => {
		codeEditor.focus();
	};

	/** Returns the currently selected text, or null when no selection. */
	export const getSelection = (): string | null => {
		if (!codeEditor) return null;
		const sel = codeEditor.state.selection.main;
		if (sel.from === sel.to) return null;
		return codeEditor.state.sliceDoc(sel.from, sel.to);
	};

	let isDarkMode = false;
	let editorTheme = new Compartment();
	let editorLanguage = new Compartment();
	let editorAutocomplete = new Compartment();

	languages.push(
		LanguageDescription.of({
			name: 'HCL',
			extensions: ['hcl', 'tf'],
			load() {
				return import('codemirror-lang-hcl').then((m) => m.hcl());
			}
		})
	);
	languages.push(
		LanguageDescription.of({
			name: 'Elixir',
			extensions: ['ex', 'exs'],
			load() {
				return import('codemirror-lang-elixir').then((m) => m.elixir());
			}
		})
	);

	const loadSqlLanguage = async () => {
		// Dynamic import keeps @codemirror/lang-sql out of the main bundle for
		// pages that don't need SQL highlighting.
		const mod = await import('@codemirror/lang-sql');
		const dialectMap = {
			postgresql: mod.PostgreSQL,
			mysql: mod.MySQL,
			mariadb: mod.MariaSQL,
			mssql: mod.MSSQL,
			sqlite: mod.SQLite,
			plsql: mod.PLSQL,
			cassandra: mod.Cassandra,
			standard: mod.StandardSQL
		} as const;
		const sqlDialect =
			(dialect && dialectMap[dialect]) || dialectMap.standard;
		const opts: { dialect: typeof sqlDialect; schema?: Record<string, string[]> } = {
			dialect: sqlDialect
		};
		if (schema && Object.keys(schema).length > 0) {
			opts.schema = schema;
		}
		return mod.sql(opts);
	};

	const getLang = async () => {
		if (lang === 'sql') {
			return await loadSqlLanguage();
		}
		const language = languages.find((l) => l.alias.includes(lang));
		return await language?.load();
	};

	export const formatPythonCodeHandler = async () => {
		if (codeEditor) {
			const res = await formatPythonCode(localStorage.token, _value).catch((error) => {
				toast.error($i18n.t(`${error}`));
				return null;
			});

			if (res && res.code) {
				const formattedCode = res.code;
				codeEditor.dispatch({
					changes: [{ from: 0, to: codeEditor.state.doc.length, insert: formattedCode }]
				});

				_value = formattedCode;
				onChange(_value);
				await tick();

				toast.success($i18n.t('Code formatted successfully'));
				return true;
			}
			return false;
		}
		return false;
	};

	let extensions = [
		basicSetup,
		// Win over basicSetup's defaultKeymap which binds Mod-Enter → insertBlankLine.
		Prec.highest(
			keymap.of([
				{
					key: 'Mod-Enter',
					run: () => {
						onRun();
						return true;
					},
					preventDefault: true
				}
			])
		),
		keymap.of([{ key: 'Tab', run: acceptCompletion }, indentWithTab]),
		indentUnit.of('    '),
		placeholder('Enter your code here...'),
		EditorView.updateListener.of((e) => {
			if (e.docChanged) {
				_value = e.state.doc.toString();
				onChange(_value);
			}
			if (e.docChanged || e.selectionSet) {
				const sel = e.state.selection.main;
				const head = sel.head;
				const line = e.state.doc.lineAt(head);
				dispatch('selectionChange', {
					line: line.number,
					col: head - line.from + 1,
					length: e.state.doc.length,
					selectionLength: Math.abs(sel.to - sel.from)
				});
			}
		}),
		// Cloo light highlight — overridden by `oneDark` (its own theme +
		// highlight pair) when the editorTheme compartment reconfigures to
		// oneDark in dark mode.
		syntaxHighlighting(cloosphereLightHighlight),
		editorTheme.of([]),
		editorLanguage.of([]),
		editorAutocomplete.of([]),
		EditorState.readOnly.of(readOnly),
		EditorView.editable.of(!readOnly),
		// Belt-and-suspenders: some input paths (synthetic events, certain IME/
		// paste) bypass EditorState.readOnly. Drop any user-originated doc change
		// when read-only; programmatic value-sync is tagged with syncAnnotation
		// and still allowed so the displayed content can update.
		EditorState.transactionFilter.of((tr) =>
			readOnly && tr.docChanged && tr.annotation(syncAnnotation) === undefined
				? []
				: tr
		)
	];

	// A single reactive trigger covers all language inputs (incl. SQL dialect
	// + schema changes). Two separate `$:` blocks both firing on mount when
	// lang='sql' caused an async race in `editorLanguage.reconfigure()`.
	$: {
		void lang;
		void dialect;
		void schema;
		if (lang) setLanguage();
	}

	const setLanguage = async () => {
		const language = await getLang();
		if (language && codeEditor) {
			const effects = [editorLanguage.reconfigure(language)];
			// SQL: trigger autocomplete on Ctrl+Space only (typing-popup is sluggish).
			if (lang === 'sql') {
				effects.push(
					editorAutocomplete.reconfigure(
						autocompletion({ activateOnTyping: false })
					)
				);
			} else {
				effects.push(editorAutocomplete.reconfigure([]));
			}
			codeEditor.dispatch({ effects });
		}
	};

	onMount(() => {
		if (value === '') {
			value = boilerplate;
		}

		_value = value;

		// Check if html class has dark mode
		isDarkMode = document.documentElement.classList.contains('dark');

		// python code editor, highlight python code
		codeEditor = new EditorView({
			state: EditorState.create({
				doc: _value,
				extensions: extensions
			}),
			parent: document.getElementById(`code-textarea-${id}`)
		});

		if (isDarkMode) {
			codeEditor.dispatch({
				effects: editorTheme.reconfigure(oneDark)
			});
		}

		// listen to html class changes this should fire only when dark mode is toggled
		const observer = new MutationObserver((mutations) => {
			mutations.forEach((mutation) => {
				if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
					const _isDarkMode = document.documentElement.classList.contains('dark');

					if (_isDarkMode !== isDarkMode) {
						isDarkMode = _isDarkMode;
						if (_isDarkMode) {
							codeEditor.dispatch({
								effects: editorTheme.reconfigure(oneDark)
							});
						} else {
							codeEditor.dispatch({
								effects: editorTheme.reconfigure()
							});
						}
					}
				}
			});
		});

		observer.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ['class']
		});

		const keydownHandler = async (e) => {
			if ((e.ctrlKey || e.metaKey) && e.key === 's') {
				e.preventDefault();

				onSave();
			}

			// Format code when Ctrl + Shift + F is pressed
			if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'f') {
				e.preventDefault();
				await formatPythonCodeHandler();
			}
		};

		document.addEventListener('keydown', keydownHandler);

		return () => {
			observer.disconnect();
			document.removeEventListener('keydown', keydownHandler);
		};
	});
</script>

<div id="code-textarea-{id}" class="cloo-codemirror-host h-full w-full text-sm" />

<style>
	/* Unify SQL code rendering across Memory modal + SQL Editor panel.
	 * Pretendard handles English & Korean at the same vertical metrics so
	 * mixed-language SQL doesn't look size-imbalanced. Falls back to system
	 * monospace if the CDN font is blocked. */
	:global(.cloo-codemirror-host .cm-editor),
	:global(.cloo-codemirror-host .cm-editor .cm-content),
	:global(.cloo-codemirror-host .cm-editor .cm-line),
	:global(.cloo-codemirror-host .cm-editor .cm-gutters) {
		font-family:
			'Pretendard Variable', 'Pretendard', -apple-system, BlinkMacSystemFont,
			'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
		font-size: 13px;
		line-height: 1.6;
		font-variant-ligatures: none;
	}
</style>
