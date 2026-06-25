(function () {
	'use strict';

	var script = document.currentScript;
	if (!script) return;

	var widgetId = script.getAttribute('data-widget-id');
	if (!widgetId) {
		console.error('[CloosphereEmbed] data-widget-id attribute is required');
		return;
	}

	var token = script.getAttribute('data-token') || '';
	var theme = script.getAttribute('data-theme') || '';
	var mode = script.getAttribute('data-mode') || '';
	var position = script.getAttribute('data-position') || '';
	var primaryColor = script.getAttribute('data-primary-color') || '';
	var target = script.getAttribute('data-target') || '';
	var widthAttr = script.getAttribute('data-width') || '';
	var heightAttr = script.getAttribute('data-height') || '';

	// Guest mode: 호스트가 자체 인증 정보를 전달할 수 있음
	var guestId = script.getAttribute('data-guest-id') || '';  // 호스트 측 유저 고유 ID (매핑 키)
	var guestName = script.getAttribute('data-guest-name') || '';
	var guestEmail = script.getAttribute('data-guest-email') || '';
	var guestContext = script.getAttribute('data-guest-context') || '';

	// API base URL (always from script src — backend serves the API)
	var apiBaseUrl = '';
	try { apiBaseUrl = new URL(script.src).origin; } catch (e) { apiBaseUrl = window.location.origin; }

	// iframe base URL (dev override → frontend dev server, otherwise same as API)
	var baseUrl = window.__CLOOSPHERE_EMBED_BASE_URL__ || apiBaseUrl;

	// Pre-init queue: 호스트가 embed.js 로드 *전*에 옵션을 큐에 넣을 수 있게.
	//   <script>window.CloosphereEmbedQ = window.CloosphereEmbedQ || {};
	//           window.CloosphereEmbedQ['<widgetId>'] = { sso: {...} };</script>
	//   <script src="…/embed.js" data-widget-id="<widgetId>"></script>
	var preInitOptions = (window.CloosphereEmbedQ && window.CloosphereEmbedQ[widgetId]) || {};

	// Fetch widget config then initialize
	var configUrl = apiBaseUrl + '/api/embed/v1/id/' + encodeURIComponent(widgetId) + '/config';
	fetch(configUrl)
		.then(function (res) { return res.ok ? res.json() : Promise.reject('Widget not found'); })
		.then(function (config) {
			var cfg = config.config || {};

			// 토큰 우선순위: data-token > SSO > Guest > iframe 처리
			if (token) {
				init(config);
				return;
			}

			// SSO 토큰이 호스트에서 미리 제공된 경우
			if (preInitOptions.sso) {
				return ssoExchange(preInitOptions.sso).then(function (jwt) {
					if (jwt) token = jwt;
					if (token) { init(config); return; }
					// SSO 실패 → guest fallback
					return tryGuestExchange(cfg, config);
				});
			}

			// Guest 모드 시도
			return tryGuestExchange(cfg, config);
		})
		.catch(function (err) { console.error('[CloosphereEmbed]', err); });

	// ---- SSO token exchange --------------------------------------------------
	// 호스트가 보유한 SSO 토큰을 백엔드로 보내 Cloosphere JWT로 교환한다.
	// 실패해도 throw하지 않고 null을 반환 — init은 진행되어 EmbedLogin이 표시됨.
	function ssoExchange(ssoOpts) {
		var url = apiBaseUrl + '/api/embed/v1/id/' + encodeURIComponent(widgetId) + '/auth/sso-exchange';
		var body = {
			provider: ssoOpts.provider,
			id_token: ssoOpts.id_token || ssoOpts.idToken || null,
			access_token: ssoOpts.access_token || ssoOpts.accessToken || null,
			issuer: ssoOpts.issuer || null
		};
		return fetch(url, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body)
		})
			.then(function (res) {
				if (!res.ok) {
					return res.json().then(function (e) {
						throw new Error(e && e.detail ? e.detail : ('HTTP ' + res.status));
					});
				}
				return res.json();
			})
			.then(function (data) {
				if (data && data.token) {
					console.log('[CloosphereEmbed] SSO exchange succeeded for', ssoOpts.provider);
					return data.token;
				}
				return null;
			})
			.catch(function (err) {
				console.warn('[CloosphereEmbed] SSO exchange failed:', err.message || err);
				return null;
			});
	}

	// ---- Guest token exchange -------------------------------------------------
	// 게스트 모드: 호스트 사용자 정보를 보내고 Cloosphere JWT를 받는다.
	function guestExchange(guestOpts) {
		var url = apiBaseUrl + '/api/embed/v1/id/' + encodeURIComponent(widgetId) + '/auth/guest';
		var body = {
			guest_id: guestOpts.guest_id || guestOpts.guestId || guestId || null,
			name: guestOpts.name || guestName || null,
			email: guestOpts.email || guestEmail || null,
			origin_url: window.location.href,
			referrer: document.referrer || null,
			user_context: null
		};
		try {
			if (guestOpts.context) {
				body.user_context = typeof guestOpts.context === 'string'
					? JSON.parse(guestOpts.context)
					: guestOpts.context;
			} else if (guestContext) {
				body.user_context = JSON.parse(guestContext);
			}
		} catch (e) { /* ignore parse errors */ }

		return fetch(url, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body)
		})
			.then(function (res) {
				if (!res.ok) {
					return res.json().then(function (e) {
						throw new Error(e && e.detail ? e.detail : ('HTTP ' + res.status));
					});
				}
				return res.json();
			})
			.then(function (data) {
				if (data && data.token) {
					console.log('[CloosphereEmbed] Guest exchange succeeded');
					return data.token;
				}
				return null;
			})
			.catch(function (err) {
				console.warn('[CloosphereEmbed] Guest exchange failed:', err.message || err);
				return null;
			});
	}

	// 게스트 모드 시도: config에 guest.enabled가 있고 조건이 맞으면 자동 교환
	function tryGuestExchange(cfg, config) {
		var guestCfg = cfg.guest || {};
		var guestInfo = preInitOptions.guest || {};
		var hasId = guestInfo.guest_id || guestInfo.guestId || guestId;
		var hasName = guestInfo.name || guestName;
		var hasEmail = guestInfo.email || guestEmail;

		if (guestCfg.enabled && (hasId || hasName || hasEmail)) {
			// 호스트가 data 속성으로 정보를 제공 → 즉시 교환 (collect_info 무관)
			return guestExchange(guestInfo).then(function (jwt) {
				if (jwt) token = jwt;
				init(config);
			});
		}

		// iframe이 처리 (EmbedLogin 또는 EmbedGuestForm)
		init(config);
	}

	function init(config) {
		var cfg = config.config || {};
		// Update UI security config (allowed_selectors, allowed_domains)
		updateUISecurity(cfg);
		// data attributes override config
		var _mode = mode || cfg.mode || 'bubble';
		console.log('[CloosphereEmbed] init - mode:', _mode, 'data-mode:', mode, 'cfg.mode:', cfg.mode);
		var _theme = theme || cfg.theme || 'auto';
		var _position = position || cfg.position || 'bottom-right';
		var _primaryColor = primaryColor || cfg.primary_color || '#171717';
		var _bubbleIconColor = cfg.bubble_icon_color || '#ffffff';
		var _headerColor = cfg.header_color || '';
		var _bubbleIconUrl = cfg.bubble_icon_url || '';
		var _width = widthAttr || cfg.width || '';
		var _height = heightAttr || cfg.height || '';
		// 버블 클릭 시 열림 형태: 'popup'(현재 동작) | 'side-right' | 'side-left' | 'side-bottom'
		var _bubbleOpenStyle = cfg.bubble_open_style || 'popup';
		// 버블 드래그 가능 여부
		var _bubbleDraggable = cfg.bubble_draggable === true;
		// 팝업 패널 사용자 리사이즈 허용 여부 (popup 모드 전용)
		var _bubbleResizable = cfg.bubble_resizable === true;
		// 버블 크기 (40~96 사이로 clamp)
		var _bubbleSize = parseInt(cfg.bubble_size, 10);
		if (!_bubbleSize || isNaN(_bubbleSize)) _bubbleSize = 56;
		_bubbleSize = Math.max(40, Math.min(96, _bubbleSize));

		var iframeSrc = baseUrl + '/embed/' + encodeURIComponent(widgetId)
			+ '?token=' + encodeURIComponent(token)
			+ '&theme=' + encodeURIComponent(_theme)
			+ (_headerColor ? '&headerColor=' + encodeURIComponent(_headerColor) : '');

		if (_mode === 'bubble') {
			initBubble(iframeSrc, _position, _primaryColor, _bubbleIconColor, _bubbleIconUrl, _width, _height, _bubbleOpenStyle, _bubbleDraggable, _bubbleSize, _bubbleResizable);
		} else if (_mode === 'side-right' || _mode === 'side-left' || _mode === 'side-bottom') {
			var sideArg = _mode === 'side-left' ? 'left' : _mode === 'side-bottom' ? 'bottom' : 'right';
			initSidePanel(iframeSrc, sideArg, _width, _height);
		} else if (_mode === 'inline') {
			initInline(iframeSrc, target, _width, _height);
		} else if (_mode === 'fullscreen') {
			initFullscreen(iframeSrc);
		}
	}

	// ---- Bubble Mode ----
	// openStyle: 'popup'(default) — bubble 위에 작은 패널 + bubble이 X로 변함
	//            'side-right' / 'side-left' — bubble 클릭 시 사이드패널처럼 풀높이로,
	//                                          bubble은 숨김. 헤더 X로만 닫음
	//            'side-bottom' — 풀너비 하단 패널, 버블 숨김, 호스트 하단 margin shift
	// draggable: true이면 사용자가 bubble을 드래그해서 옮길 수 있음 (위치는 localStorage 저장)
	// bubbleSize: 버블 지름(px)
	function initBubble(iframeSrc, position, color, iconColor, iconUrl, customWidth, customHeight, openStyle, draggable, bubbleSize, resizable) {
		var Z = 9999;
		var BUBBLE_SIZE = bubbleSize || 56;
		// 아이콘 크기는 버블 크기의 50% 정도가 적절
		var ICON_SIZE = Math.round(BUBBLE_SIZE * 0.5);
		var MARGIN = 16;
		var isOpen = false;
		var isRight = position !== 'bottom-left';
		var isSide = openStyle === 'side-right' || openStyle === 'side-left' || openStyle === 'side-bottom';
		var sideDir = openStyle === 'side-left' ? 'left' : openStyle === 'side-bottom' ? 'bottom' : 'right';
		var isBottom = sideDir === 'bottom';

		var bubble = document.createElement('div');
		bubble.id = 'cloosphere-embed-bubble';
		Object.assign(bubble.style, {
			position: 'fixed',
			bottom: MARGIN + 'px',
			zIndex: Z,
			width: BUBBLE_SIZE + 'px',
			height: BUBBLE_SIZE + 'px',
			borderRadius: '50%',
			background: color,
			color: iconColor,
			cursor: 'pointer',
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
			transition: 'transform 0.2s, box-shadow 0.2s, opacity 0.2s'
		});
		bubble.style[isRight ? 'right' : 'left'] = MARGIN + 'px';

		// Render bubble icon
		function buildIcon() {
			if (!iconUrl) return chatIcon(ICON_SIZE);
			if (iconUrl.indexOf('data:image/svg+xml') === 0) {
				try {
					var svgText = decodeURIComponent(iconUrl.replace('data:image/svg+xml;utf8,', ''));
					return svgText.replace('<svg', '<svg width="' + ICON_SIZE + '" height="' + ICON_SIZE + '"');
				} catch (e) {
					return chatIcon(ICON_SIZE);
				}
			}
			return '<img src="' + iconUrl + '" style="width:' + ICON_SIZE + 'px;height:' + ICON_SIZE + 'px;border-radius:50%;object-fit:cover;" />';
		}
		var defaultBubbleIcon = buildIcon();
		bubble.innerHTML = defaultBubbleIcon;

		bubble.onmouseenter = function () { bubble.style.transform = 'scale(1.08)'; bubble.style.boxShadow = '0 6px 20px rgba(0,0,0,0.2)'; };
		bubble.onmouseleave = function () { bubble.style.transform = 'scale(1)'; bubble.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)'; };

		var panel = document.createElement('div');
		panel.id = 'cloosphere-embed-panel';
		var panelW, panelH, panelMaxH, popupBaseStyle;

		if (isSide && isBottom) {
			// 하단 사이드 패널: 풀 너비 + 화면 하단에 붙음
			panelW = '100vw';
			panelH = customHeight || '320px';
			panelMaxH = '100vh';
			popupBaseStyle = {
				position: 'fixed',
				left: '0',
				right: '0',
				bottom: '0',
				zIndex: Z,
				width: panelW,
				height: panelH,
				maxHeight: panelMaxH,
				overflow: 'hidden',
				boxShadow: '0 -2px 12px rgba(0,0,0,0.12)',
				display: 'none',
				opacity: '0',
				transform: 'translateY(16px)',
				transition: 'opacity 0.2s, transform 0.2s'
			};
		} else if (isSide) {
			// 사이드 패널 형태: 풀 높이 + 화면 옆에 붙음
			// iOS Safari 주소창 이슈 때문에 100dvh 선호 (미지원 시 100vh fallback)
			var sideVhUnit = (window.CSS && CSS.supports && CSS.supports('height: 100dvh')) ? '100dvh' : '100vh';
			panelW = customWidth || '400px';
			panelH = sideVhUnit;
			panelMaxH = sideVhUnit;
			popupBaseStyle = {
				position: 'fixed',
				top: '0',
				bottom: '0',
				zIndex: Z,
				width: panelW,
				height: panelH,
				maxHeight: panelMaxH,
				overflow: 'hidden',
				boxShadow: sideDir === 'right' ? '-2px 0 12px rgba(0,0,0,0.12)' : '2px 0 12px rgba(0,0,0,0.12)',
				display: 'none',
				opacity: '0',
				transform: sideDir === 'right' ? 'translateX(16px)' : 'translateX(-16px)',
				transition: 'opacity 0.2s, transform 0.2s'
			};
		} else {
			// 팝업 형태: bubble 위에 floating
			panelW = customWidth || '400px';
			panelH = customHeight || '600px';
			panelMaxH = 'calc(100vh - ' + (MARGIN * 2 + BUBBLE_SIZE + 12) + 'px)';
			popupBaseStyle = {
				position: 'fixed',
				bottom: (MARGIN + BUBBLE_SIZE + 12) + 'px',
				zIndex: Z,
				width: panelW,
				height: panelH,
				maxHeight: panelMaxH,
				borderRadius: '12px',
				overflow: 'hidden',
				boxShadow: '0 8px 30px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.08)',
				display: 'none',
				opacity: '0',
				transform: 'translateY(8px)',
				transition: 'opacity 0.2s, transform 0.2s'
			};
		}
		Object.assign(panel.style, popupBaseStyle);
		panel.style[isSide ? sideDir : (isRight ? 'right' : 'left')] = isSide ? '0' : (MARGIN + 'px');

		var iframe = createIframe(iframeSrc);
		panel.appendChild(iframe);

		// 사이드 패널 크기를 호스트 문서에 publish. 3계층:
		//   1. 호스트 레이아웃 shift — 가로(right/left): body margin 조정, 하단: html height 제약
		//      (body margin-bottom 은 content 를 위로 밀지 못하기 때문에 html height 를 줄여서 viewport 를 제약)
		//   2. CSS 변수 설정 (세밀 제어용) — 가로 사이드: --cloosphere-side-panel-width,
		//                                    하단 사이드: --cloosphere-side-panel-height
		//   3. `cloosphere:side-resize` 이벤트 디스패치 (JS hook 용) — detail 에 width/height 모두 포함
		// 레이아웃 shift 는 호스트가 data-cloosphere-no-shift 속성을 body 에 두면 비활성.
		var SIDE_EVENT = 'cloosphere:side-resize';
		var SIDE_CSS_VAR = isBottom ? '--cloosphere-side-panel-height' : '--cloosphere-side-panel-width';
		var bodyMarginProp = 'margin' + (sideDir === 'right' ? 'Right' : 'Left');
		var prevBodyMargin = '';
		var bodyMarginCaptured = false;
		var prevHtmlHeight = '';
		var htmlHeightCaptured = false;
		function publishSideWidth() {
			if (!isSide) return;
			var rect = panel.getBoundingClientRect();
			var size = isOpen ? Math.round(isBottom ? rect.height : rect.width) : 0;
			try {
				document.documentElement.style.setProperty(SIDE_CSS_VAR, size + 'px');
				document.dispatchEvent(new CustomEvent(SIDE_EVENT, { detail: {
					width: isBottom ? 0 : size,
					height: isBottom ? size : 0,
					side: sideDir,
					open: isOpen
				} }));
			} catch (_) {}
			// 호스트 레이아웃 shift (opt-out 가능)
			if (document.body.hasAttribute('data-cloosphere-no-shift')) return;
			if (isBottom) {
				// 하단: html height 를 viewport - panel 로 제약 → content 가 위 공간으로 reflow
				var htmlStyle = document.documentElement.style;
				if (!htmlHeightCaptured) {
					prevHtmlHeight = htmlStyle.height || '';
					htmlHeightCaptured = true;
				}
				if (!htmlStyle.transition || htmlStyle.transition.indexOf('height') === -1) {
					htmlStyle.transition = (htmlStyle.transition ? htmlStyle.transition + ', ' : '') + 'height 0.22s ease';
				}
				htmlStyle.height = size > 0 ? 'calc(100vh - ' + size + 'px)' : prevHtmlHeight;
			} else {
				// 가로: body margin 으로 content 밀기
				if (!bodyMarginCaptured) {
					prevBodyMargin = document.body.style[bodyMarginProp] || '';
					bodyMarginCaptured = true;
				}
				var bodyStyle = document.body.style;
				if (!bodyStyle.transition || bodyStyle.transition.indexOf(bodyMarginProp) === -1) {
					bodyStyle.transition = (bodyStyle.transition ? bodyStyle.transition + ', ' : '') + bodyMarginProp.replace(/([A-Z])/g, '-$1').toLowerCase() + ' 0.22s ease';
				}
				bodyStyle[bodyMarginProp] = size > 0 ? size + 'px' : prevBodyMargin;
			}
		}

		function open() {
			isOpen = true;
			panel.style.display = 'block';
			requestAnimationFrame(function () {
				panel.style.opacity = '1';
				panel.style.transform = (isSide && !isBottom) ? 'translateX(0)' : 'translateY(0)';
				publishSideWidth();
			});
			if (isSide) {
				// 사이드 모드: bubble 숨김
				bubble.style.opacity = '0';
				bubble.style.pointerEvents = 'none';
			} else {
				// 팝업 모드: bubble을 X 아이콘으로 토글
				bubble.innerHTML = closeIcon(ICON_SIZE);
			}
		}
		function close() {
			isOpen = false;
			panel.style.opacity = '0';
			panel.style.transform = isBottom
				? 'translateY(16px)'
				: isSide
					? (sideDir === 'right' ? 'translateX(16px)' : 'translateX(-16px)')
					: 'translateY(8px)';
			setTimeout(function () { if (!isOpen) panel.style.display = 'none'; }, 200);
			if (isSide) {
				bubble.style.opacity = '1';
				bubble.style.pointerEvents = '';
				publishSideWidth();
			} else {
				bubble.innerHTML = defaultBubbleIcon;
			}
		}

		bubble.onclick = function () { isOpen ? close() : open(); };

		// ---- Draggable bubble ----
		// 사용자가 버블을 드래그해서 옮길 수 있게. 위치는 widgetId 별로 localStorage에 저장.
		// 드래그가 끝났을 때 가까운 좌/우 가장자리로 snap.
		var dragMoved = false;
		if (draggable) {
			var storageKey = 'cloosphere_embed_bubble_pos_' + widgetId;
			var dragStartX = 0, dragStartY = 0;
			var dragStartLeft = 0, dragStartTop = 0;
			var dragging = false;
			var pointerId = null;

			function applyStoredPos() {
				try {
					var raw = localStorage.getItem(storageKey);
					if (!raw) return;
					var pos = JSON.parse(raw);
					if (typeof pos.left === 'number' && typeof pos.top === 'number') {
						bubble.style.left = pos.left + 'px';
						bubble.style.top = pos.top + 'px';
						bubble.style.right = 'auto';
						bubble.style.bottom = 'auto';
					}
				} catch (e) { /* ignore */ }
			}
			applyStoredPos();

			function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }

			bubble.style.touchAction = 'none';

			function onPointerDown(e) {
				if (e.button !== undefined && e.button !== 0) return;
				pointerId = e.pointerId;
				dragging = false; // 실제 이동 발생 시 true (클릭과 구분)
				dragStartX = e.clientX;
				dragStartY = e.clientY;
				var rect = bubble.getBoundingClientRect();
				dragStartLeft = rect.left;
				dragStartTop = rect.top;
				bubble.setPointerCapture(pointerId);
			}

			function onPointerMove(e) {
				if (pointerId === null || e.pointerId !== pointerId) return;
				var dx = e.clientX - dragStartX;
				var dy = e.clientY - dragStartY;
				if (!dragging && (Math.abs(dx) > 4 || Math.abs(dy) > 4)) {
					dragging = true;
					dragMoved = true;
					bubble.style.transition = 'none';
				}
				if (!dragging) return;
				var newLeft = clamp(dragStartLeft + dx, MARGIN, window.innerWidth - BUBBLE_SIZE - MARGIN);
				var newTop = clamp(dragStartTop + dy, MARGIN, window.innerHeight - BUBBLE_SIZE - MARGIN);
				bubble.style.left = newLeft + 'px';
				bubble.style.top = newTop + 'px';
				bubble.style.right = 'auto';
				bubble.style.bottom = 'auto';
			}

			function onPointerUp(e) {
				if (pointerId === null || e.pointerId !== pointerId) return;
				try { bubble.releasePointerCapture(pointerId); } catch (_) {}
				pointerId = null;
				if (!dragging) return;
				bubble.style.transition = 'transform 0.2s, box-shadow 0.2s, opacity 0.2s, left 0.25s, top 0.25s';
				// Snap to nearest horizontal edge
				var rect = bubble.getBoundingClientRect();
				var snapLeft = rect.left + BUBBLE_SIZE / 2 < window.innerWidth / 2
					? MARGIN
					: window.innerWidth - BUBBLE_SIZE - MARGIN;
				bubble.style.left = snapLeft + 'px';
				try {
					localStorage.setItem(storageKey, JSON.stringify({ left: snapLeft, top: rect.top }));
				} catch (_) {}
				// 드래그 직후 click 이벤트 막기 (핸들러는 1회용)
				var blockClick = function (ev) {
					ev.stopPropagation();
					ev.preventDefault();
					bubble.removeEventListener('click', blockClick, true);
				};
				bubble.addEventListener('click', blockClick, true);
			}

			bubble.addEventListener('pointerdown', onPointerDown);
			bubble.addEventListener('pointermove', onPointerMove);
			bubble.addEventListener('pointerup', onPointerUp);
			bubble.addEventListener('pointercancel', onPointerUp);
		}

		// ---- Resizable panel ----
		// popup 모드: 상단 모서리에 대각선 그립 → width/height 양방향 조정
		// side-right/left: 안쪽 세로 edge 에 수직 그립 → width 만 조정 (height 는 100vh)
		// side-bottom: 상단 edge 에 수평 그립 → height 만 조정 (width 는 100vw)
		// 크기는 widgetId 별 localStorage 에 저장되어 재방문 시 복원된다.
		var isUserResized = false;
		if (resizable) {
			var sizeKey = 'cloosphere_embed_panel_size_' + widgetId;
			var MIN_W = 320, MIN_H = 360;
			var maxW = function () { return window.innerWidth - (isSide ? 0 : MARGIN * 2); };
			var maxH = function () { return window.innerHeight - (isSide ? 0 : (MARGIN * 2 + BUBBLE_SIZE + 12)); };
			var grip = document.createElement('div');
			grip.setAttribute('aria-label', 'resize');
			panel.style.position = 'fixed';

			if (isSide && isBottom) {
				// 하단 사이드 모드: 패널 상단 edge 에 수평 그립 → height 만 조정
				Object.assign(grip.style, {
					position: 'absolute',
					left: '0',
					right: '0',
					top: '-3px',
					height: '6px',
					cursor: 'ns-resize',
					zIndex: '2',
					touchAction: 'none',
					background: 'transparent'
				});
				grip.addEventListener('mouseenter', function () { grip.style.background = 'rgba(0,0,0,0.08)'; });
				grip.addEventListener('mouseleave', function () { grip.style.background = 'transparent'; });
			} else if (isSide) {
				// 사이드 모드: 패널의 안쪽 세로 edge 에 세로 그립
				// side-right → 패널이 오른쪽 → 그립은 왼쪽 edge
				// side-left  → 패널이 왼쪽   → 그립은 오른쪽 edge
				var sideGripEdge = sideDir === 'right' ? 'left' : 'right';
				Object.assign(grip.style, {
					position: 'absolute',
					top: '0',
					bottom: '0',
					width: '6px',
					cursor: 'ew-resize',
					zIndex: '2',
					touchAction: 'none',
					background: 'transparent'
				});
				grip.style[sideGripEdge] = '-3px';
				grip.addEventListener('mouseenter', function () { grip.style.background = 'rgba(0,0,0,0.08)'; });
				grip.addEventListener('mouseleave', function () { grip.style.background = 'transparent'; });
			} else {
				// 팝업 모드: 패널 상단 모서리(버블 반대쪽)에 대각선 그립
				var gripCorner = isRight ? 'left' : 'right';
				Object.assign(grip.style, {
					position: 'absolute',
					top: '0',
					width: '14px',
					height: '14px',
					cursor: isRight ? 'nwse-resize' : 'nesw-resize',
					zIndex: '2',
					touchAction: 'none',
					background:
						'linear-gradient(' + (isRight ? '135deg' : '45deg') +
						', transparent 45%, rgba(0,0,0,0.25) 45%, rgba(0,0,0,0.25) 55%, transparent 55%)'
				});
				grip.style[gripCorner] = '0';
			}
			panel.appendChild(grip);

			function restoreSize() {
				try {
					var raw = localStorage.getItem(sizeKey);
					if (!raw) return;
					var s = JSON.parse(raw);
					// 하단 사이드 모드는 width 가 고정(100vw)이므로 width 복원 skip
					if (!isBottom && typeof s.w === 'number') {
						var w = Math.max(MIN_W, Math.min(s.w, maxW()));
						panelW = w + 'px';
						panel.style.width = panelW;
						isUserResized = true;
					}
					// popup 또는 side-bottom 은 height 복원
					if ((!isSide || isBottom) && typeof s.h === 'number') {
						var h = Math.max(MIN_H, Math.min(s.h, maxH()));
						panelH = h + 'px';
						panel.style.height = panelH;
						isUserResized = true;
					}
				} catch (_) {}
			}
			restoreSize();

			var rPointer = null, rStartX = 0, rStartY = 0, rStartW = 0, rStartH = 0;
			grip.addEventListener('pointerdown', function (e) {
				if (e.button !== undefined && e.button !== 0) return;
				e.preventDefault();
				e.stopPropagation();
				rPointer = e.pointerId;
				var rect = panel.getBoundingClientRect();
				rStartX = e.clientX;
				rStartY = e.clientY;
				rStartW = rect.width;
				rStartH = rect.height;
				grip.setPointerCapture(rPointer);
				panel.style.transition = 'none';
			});
			grip.addEventListener('pointermove', function (e) {
				if (rPointer === null || e.pointerId !== rPointer) return;
				// 확장 방향은 패널이 고정된 edge 반대쪽
				// popup: isRight=true 면 패널이 오른쪽 → 왼쪽으로 당겨야 width 증가
				// side-right (isRight=true, isSide): 동일
				// side-left  (isRight=false, isSide): 오른쪽으로 당겨야 width 증가
				// side-bottom: width 고정, 위로 당기면 height 증가
				if (!isBottom) {
					var dx = isRight ? (rStartX - e.clientX) : (e.clientX - rStartX);
					var newW = Math.max(MIN_W, Math.min(rStartW + dx, maxW()));
					panel.style.width = newW + 'px';
					panelW = newW + 'px';
				}

				if (!isSide || isBottom) {
					var dy = rStartY - e.clientY; // 위로 당기면 height 증가
					var newH = Math.max(MIN_H, Math.min(rStartH + dy, maxH()));
					panel.style.height = newH + 'px';
					panelH = newH + 'px';
				}
				isUserResized = true;
				publishSideWidth();
			});
			function endResize(e) {
				if (rPointer === null || e.pointerId !== rPointer) return;
				try { grip.releasePointerCapture(rPointer); } catch (_) {}
				rPointer = null;
				panel.style.transition = 'opacity 0.2s, transform 0.2s';
				try {
					var rect = panel.getBoundingClientRect();
					// side-bottom: height 만 저장 (width 는 100vw 고정)
					// popup: width + height
					// side-left/right: width 만 저장 (height 는 100vh 고정)
					var payload = isBottom
						? { h: Math.round(rect.height) }
						: { w: Math.round(rect.width) };
					if (!isSide) payload.h = Math.round(rect.height);
					localStorage.setItem(sizeKey, JSON.stringify(payload));
				} catch (_) {}
			}
			grip.addEventListener('pointerup', endResize);
			grip.addEventListener('pointercancel', endResize);
		}

		// Responsive — 모바일(<=480px)에서는 모든 모드가 전체 뷰포트를 차지
		var mq = window.matchMedia('(max-width: 480px)');
		var dvhSupported = window.CSS && CSS.supports && CSS.supports('height: 100dvh');
		var fullVh = dvhSupported ? '100dvh' : '100vh';
		function handleMq(e) {
			if (e.matches) {
				if (isSide && isBottom) {
					// 하단 사이드: 너비는 이미 100vw, 높이만 모바일에서 살짝 확대
					panel.style.width = '100vw';
					panel.style.height = customHeight || '70vh';
					panel.style.maxHeight = fullVh;
				} else if (isSide) {
					// right/left 사이드: 풀스크린 오버레이
					panel.style.width = '100vw';
					panel.style.height = fullVh;
					panel.style.maxHeight = fullVh;
				} else {
					// 팝업: bubble 위 floating
					panel.style.width = 'calc(100vw - ' + (MARGIN * 2) + 'px)';
					panel.style.height = 'calc(' + fullVh + ' - ' + (MARGIN * 2 + BUBBLE_SIZE + 12) + 'px)';
					panel.style.maxHeight = '80vh';
				}
			} else if (!isUserResized) {
				panel.style.width = panelW;
				panel.style.height = panelH;
				panel.style.maxHeight = panelMaxH;
			}
		}
		handleMq(mq);
		mq.addListener(handleMq);

		document.body.appendChild(bubble);
		document.body.appendChild(panel);

		setPublicAPI(open, close);
	}

	// ---- Side Panel Mode ----
	// side: 'right' | 'left' | 'bottom'
	//   - right/left: 풀 높이, customWidth 적용, body margin 으로 호스트 shift
	//   - bottom:    풀 너비, customHeight 적용, html height 제약으로 호스트 shift
	function initSidePanel(iframeSrc, side, customWidth, customHeight) {
		var isBottom = side === 'bottom';
		var panelWidth = customWidth || '380px';
		var panelHeight = customHeight || '320px';
		// iOS Safari 주소창 이슈: 100dvh 선호, 미지원 시 100vh fallback
		var dvhSupported = window.CSS && CSS.supports && CSS.supports('height: 100dvh');
		var fullVh = dvhSupported ? '100dvh' : '100vh';
		var panel = document.createElement('div');
		panel.id = 'cloosphere-embed-side';
		if (isBottom) {
			Object.assign(panel.style, {
				position: 'fixed',
				left: '0',
				right: '0',
				bottom: '0',
				height: panelHeight,
				zIndex: '9999',
				boxShadow: '0 -2px 8px rgba(0,0,0,0.1)'
			});
		} else {
			Object.assign(panel.style, {
				position: 'fixed',
				top: '0',
				bottom: '0',
				width: panelWidth,
				zIndex: '9999',
				boxShadow: side === 'right' ? '-2px 0 8px rgba(0,0,0,0.1)' : '2px 0 8px rgba(0,0,0,0.1)'
			});
			panel.style[side] = '0';
		}

		var iframe = createIframe(iframeSrc);
		panel.appendChild(iframe);
		document.body.appendChild(panel);

		// 모바일에서는 body margin 으로 페이지를 380px 씩 미는 순간 화면 밖으로 밀려나므로,
		// 풀스크린 오버레이로 바꾸고 shift 를 해제한다.
		var canShift = !document.body.hasAttribute('data-cloosphere-no-shift');
		var sideProp = isBottom ? null : ('margin' + (side === 'right' ? 'Right' : 'Left'));

		function applyLayout(isMobile) {
			if (isMobile) {
				if (isBottom) {
					panel.style.height = fullVh;
					panel.style.width = '100vw';
					document.documentElement.style.height = '';
				} else {
					panel.style.width = '100vw';
					panel.style.height = fullVh;
					if (sideProp) document.body.style[sideProp] = '';
				}
			} else {
				if (isBottom) {
					panel.style.width = '';
					panel.style.height = panelHeight;
					if (canShift) {
						// html height 를 viewport - panel 로 제약 → content 가 위 공간으로 reflow
						document.documentElement.style.height = 'calc(' + fullVh + ' - ' + panelHeight + ')';
					}
				} else {
					panel.style.width = panelWidth;
					panel.style.height = '';
					if (canShift && sideProp) {
						document.body.style[sideProp] = panelWidth;
					}
				}
			}
		}

		var mq = window.matchMedia('(max-width: 480px)');
		applyLayout(mq.matches);
		mq.addListener(function (e) { applyLayout(e.matches); });

		setPublicAPI(function () {}, function () {});
	}

	// ---- Inline Mode ----
	function initInline(iframeSrc, targetSelector, customWidth, customHeight) {
		var container = targetSelector ? document.querySelector(targetSelector) : null;
		if (!container) {
			container = document.createElement('div');
			container.id = 'cloosphere-embed-inline';
			Object.assign(container.style, { width: customWidth || '100%', height: customHeight || '500px' });
			script.parentNode.insertBefore(container, script.nextSibling);
		}

		var iframe = createIframe(iframeSrc);
		iframe.style.borderRadius = '12px';
		iframe.style.border = '1px solid #e5e5e5';
		container.appendChild(iframe);

		setPublicAPI(function () {}, function () {});
	}

	// ---- Fullscreen Mode ----
	function initFullscreen(iframeSrc) {
		var container = document.createElement('div');
		container.id = 'cloosphere-embed-fullscreen';
		Object.assign(container.style, {
			position: 'fixed',
			top: '0', left: '0', right: '0', bottom: '0',
			zIndex: '9999'
		});

		var iframe = createIframe(iframeSrc);
		container.appendChild(iframe);
		document.body.appendChild(container);

		setPublicAPI(function () {}, function () {});
	}

	// ---- Helpers ----
	function createIframe(src) {
		var iframe = document.createElement('iframe');
		iframe.src = src;
		iframe.setAttribute('allow', 'clipboard-write');
		Object.assign(iframe.style, { width: '100%', height: '100%', border: 'none' });
		return iframe;
	}

	function setPublicAPI(openFn, closeFn) {
		function pushTokenToIframes(t) {
			var iframes = document.querySelectorAll('iframe[src*="/embed/"]');
			iframes.forEach(function (iframe) {
				try {
					iframe.contentWindow.postMessage({ type: 'token-update', token: t }, baseUrl);
				} catch (e) {
					/* ignore cross-origin errors */
				}
			});
		}

		window.CloosphereEmbed = {
			open: openFn,
			close: closeFn,
			toggle: function () { /* bubble only */ },
			updateToken: function (t) {
				token = t;
				pushTokenToIframes(t);
			},
			// 호스트가 init 후에 SSO 토큰을 받았을 때 호출
			// 예) CloosphereEmbed.ssoLogin({provider:'microsoft', id_token:'...'})
			ssoLogin: function (ssoOpts) {
				return ssoExchange(ssoOpts).then(function (jwt) {
					if (jwt) {
						token = jwt;
						pushTokenToIframes(jwt);
					}
					return jwt;
				});
			},
			// 호스트가 게스트 사용자 정보를 전달하여 JWT를 발급받을 때 호출
			// 예) CloosphereEmbed.guestLogin({name:'홍길동', email:'hong@ex.com', context:{dept:'영업팀'}})
			guestLogin: function (guestOpts) {
				return guestExchange(guestOpts || {}).then(function (jwt) {
					if (jwt) {
						token = jwt;
						pushTokenToIframes(jwt);
					}
					return jwt;
				});
			}
		};
	}

	function chatIcon(size) {
		var s = size || 28;
		return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="' + s + '" height="' + s + '">'
			+ '<path fill-rule="evenodd" d="M4.848 2.771A49.144 49.144 0 0 1 12 2.25c2.43 0 4.817.178 7.152.52 1.978.292 3.348 2.024 3.348 3.97v6.02c0 1.946-1.37 3.678-3.348 3.97a48.901 48.901 0 0 1-3.476.383.39.39 0 0 0-.297.17l-2.755 4.133a.75.75 0 0 1-1.248 0l-2.755-4.133a.39.39 0 0 0-.297-.17 48.9 48.9 0 0 1-3.476-.384c-1.978-.29-3.348-2.024-3.348-3.97V6.741c0-1.946 1.37-3.68 3.348-3.97Z" clip-rule="evenodd"/>'
			+ '</svg>';
	}

	function closeIcon(size) {
		var s = size || 28;
		return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="' + s + '" height="' + s + '">'
			+ '<path fill-rule="evenodd" d="M5.47 5.47a.75.75 0 0 1 1.06 0L12 10.94l5.47-5.47a.75.75 0 1 1 1.06 1.06L13.06 12l5.47 5.47a.75.75 0 1 1-1.06 1.06L12 13.06l-5.47 5.47a.75.75 0 0 1-1.06-1.06L10.94 12 5.47 6.53a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd"/>'
			+ '</svg>';
	}

	// ============================================================
	// UI Command Bridge
	// ============================================================
	// Allows the AI agent (running inside the iframe) to manipulate
	// the parent page's DOM via postMessage.
	//
	// Supported commands:
	//   - ui:fill-field     → Set value of an input/textarea/select
	//   - ui:fill-form      → Fill multiple fields at once
	//   - ui:click          → Click an element
	//   - ui:read-form      → Read form values into JSON
	//   - ui:highlight      → Highlight + scroll an element
	//   - ui:navigate       → Navigate the parent page
	//
	// Security: Each command must pass selector allow-list check.
	// The widget config.allowed_selectors array controls which
	// selectors are allowed (defaults to ['*'] if not specified).
	// ============================================================

	var _uiAllowedSelectors = ['*'];
	var _uiAllowedDomains = [];

	function updateUISecurity(cfg) {
		if (cfg && Array.isArray(cfg.allowed_selectors) && cfg.allowed_selectors.length > 0) {
			_uiAllowedSelectors = cfg.allowed_selectors;
		}
		if (cfg && Array.isArray(cfg.allowed_domains)) {
			_uiAllowedDomains = cfg.allowed_domains;
		}
	}

	function isSelectorAllowed(selector) {
		if (!selector || typeof selector !== 'string') return false;
		if (_uiAllowedSelectors.indexOf('*') !== -1) return true;
		for (var i = 0; i < _uiAllowedSelectors.length; i++) {
			var pattern = _uiAllowedSelectors[i];
			if (selector === pattern) return true;
			// Basic prefix match: "form#leave-form *" allows anything inside
			if (pattern.indexOf('*') !== -1) {
				var prefix = pattern.replace(/\s*\*\s*$/, '');
				if (selector.indexOf(prefix) === 0) return true;
			}
		}
		return false;
	}

	function setNativeValue(el, value) {
		var proto = Object.getPrototypeOf(el);
		var setter = Object.getOwnPropertyDescriptor(proto, 'value');
		if (setter && setter.set) {
			setter.set.call(el, value);
		} else {
			el.value = value;
		}
		el.dispatchEvent(new Event('input', { bubbles: true }));
		el.dispatchEvent(new Event('change', { bubbles: true }));
	}

	function fillField(selector, value) {
		if (!isSelectorAllowed(selector)) {
			return { ok: false, error: 'Selector not allowed: ' + selector };
		}
		var el = document.querySelector(selector);
		if (!el) return { ok: false, error: 'Element not found: ' + selector };
		try {
			setNativeValue(el, value);
			return { ok: true };
		} catch (e) {
			return { ok: false, error: String(e) };
		}
	}

	function fillForm(formSelector, data) {
		if (!isSelectorAllowed(formSelector)) {
			return { ok: false, error: 'Form selector not allowed: ' + formSelector };
		}
		var form = document.querySelector(formSelector);
		if (!form) return { ok: false, error: 'Form not found: ' + formSelector };
		var results = {};
		Object.keys(data || {}).forEach(function (key) {
			// Try multiple selector strategies: #{key}, [name="{key}"]
			var el = form.querySelector('#' + key) || form.querySelector('[name="' + key + '"]');
			if (!el) {
				results[key] = { ok: false, error: 'Field not found' };
				return;
			}
			try {
				setNativeValue(el, data[key]);
				results[key] = { ok: true };
			} catch (e) {
				results[key] = { ok: false, error: String(e) };
			}
		});
		return { ok: true, fields: results };
	}

	function clickElement(selector) {
		if (!isSelectorAllowed(selector)) {
			return { ok: false, error: 'Selector not allowed: ' + selector };
		}
		var el = document.querySelector(selector);
		if (!el) return { ok: false, error: 'Element not found: ' + selector };
		try {
			el.click();
			return { ok: true };
		} catch (e) {
			return { ok: false, error: String(e) };
		}
	}

	function readForm(formSelector) {
		if (!isSelectorAllowed(formSelector)) {
			return { ok: false, error: 'Form selector not allowed: ' + formSelector };
		}
		var form = document.querySelector(formSelector);
		if (!form) return { ok: false, error: 'Form not found: ' + formSelector };
		var data = {};
		var inputs = form.querySelectorAll('input, textarea, select');
		inputs.forEach(function (el) {
			var key = el.name || el.id;
			if (!key) return;
			if (el.type === 'checkbox' || el.type === 'radio') {
				data[key] = el.checked;
			} else {
				data[key] = el.value;
			}
		});
		return { ok: true, data: data };
	}

	function highlightElement(selector, message) {
		if (!isSelectorAllowed(selector)) {
			return { ok: false, error: 'Selector not allowed: ' + selector };
		}
		var el = document.querySelector(selector);
		if (!el) return { ok: false, error: 'Element not found: ' + selector };
		try {
			el.scrollIntoView({ behavior: 'smooth', block: 'center' });
			var prevOutline = el.style.outline;
			var prevOffset = el.style.outlineOffset;
			el.style.outline = '3px solid #3b82f6';
			el.style.outlineOffset = '2px';
			setTimeout(function () {
				el.style.outline = prevOutline;
				el.style.outlineOffset = prevOffset;
			}, 2500);
			return { ok: true, message: message || null };
		} catch (e) {
			return { ok: false, error: String(e) };
		}
	}

	// _softNavHandled is set to true when the host page (groupware) handles
	// the navigation via its own router. We listen for the ack.
	var _softNavAck = false;
	window.addEventListener('message', function (event) {
		if (event.data && event.data.type === 'cloosphere:navigation-handled') {
			_softNavAck = true;
		}
	});

	function navigateTo(url) {
		try {
			var u = new URL(url, window.location.href);
			// If allowed_domains is set, enforce same-host check
			if (_uiAllowedDomains.length > 0) {
				var matched = false;
				for (var i = 0; i < _uiAllowedDomains.length; i++) {
					var pat = _uiAllowedDomains[i].replace(/^\*\./, '');
					if (u.hostname === pat || u.hostname.endsWith('.' + pat)) {
						matched = true;
						break;
					}
				}
				if (!matched) {
					return { ok: false, error: 'Domain not allowed: ' + u.hostname };
				}
			}

			// Try soft navigation: post a custom event on the parent page.
			// If the host page integrated a listener (e.g. calls router.push()),
			// it will navigate without reloading the iframe.
			var sameOrigin = u.origin === window.location.origin;
			if (sameOrigin) {
				_softNavAck = false;
				try {
					// Dispatch on the parent window itself
					window.dispatchEvent(
						new CustomEvent('cloosphere:navigate', {
							detail: { url: u.href, pathname: u.pathname }
						})
					);
					// Brief wait for the host to acknowledge
					return new Promise(function (resolve) {
						setTimeout(function () {
							if (_softNavAck) {
								resolve({ ok: true, soft: true });
							} else {
								// Host didn't handle it → hard navigation
								window.location.href = u.href;
								resolve({ ok: true, soft: false });
							}
						}, 200);
					});
				} catch (softErr) {
					// Fall through to hard navigation
				}
			}

			// Hard navigation (full page reload)
			window.location.href = u.href;
			return { ok: true, soft: false };
		} catch (e) {
			return { ok: false, error: String(e) };
		}
	}

	function getPageInfo() {
		var forms = [];
		document.querySelectorAll('form').forEach(function (f) {
			forms.push({
				id: f.id || null,
				action: f.action || null,
				fields: Array.from(f.elements).map(function (el) {
					return { name: el.name || null, id: el.id || null, type: el.type || null };
				}).filter(function (x) { return x.name || x.id; })
			});
		});
		return {
			ok: true,
			url: window.location.href,
			pathname: window.location.pathname,
			title: document.title,
			forms: forms
		};
	}

	function executeUICommand(command, args) {
		args = args || {};
		switch (command) {
			case 'fill-field':
				return fillField(args.selector, args.value);
			case 'fill-form':
				return fillForm(args.form_selector || args.selector, args.data);
			case 'click':
				return clickElement(args.selector);
			case 'read-form':
				return readForm(args.form_selector || args.selector);
			case 'highlight':
				return highlightElement(args.selector, args.message);
			case 'navigate':
				return navigateTo(args.url);
			case 'get-page-info':
				return getPageInfo();
			default:
				return { ok: false, error: 'Unknown command: ' + command };
		}
	}

	// Listen for messages from iframe
	window.addEventListener('message', function (event) {
		if (event.origin !== baseUrl) return;
		var data = event.data;
		if (!data || typeof data !== 'object') return;

		if (data.type === 'close-widget' && window.CloosphereEmbed) {
			window.CloosphereEmbed.close();
			return;
		}

		if (data.type === 'cloosphere:ui-command') {
			var rawResult = executeUICommand(data.command, data.args);
			// Result may be a Promise (navigate uses async soft-nav)
			Promise.resolve(rawResult).then(function (result) {
				var iframes = document.querySelectorAll('iframe[src*="/embed/"]');
				iframes.forEach(function (iframe) {
					try {
						iframe.contentWindow.postMessage(
							{
								type: 'cloosphere:ui-result',
								request_id: data.request_id,
								result: result
							},
							baseUrl
						);
					} catch (e) {
						/* ignore */
					}
				});
			});
		}
	});

})();
