/* Decision-tree editor: view switching, graph node selection, resizable
   sidebar, and graph zoom. Extracted from decision_tree/editor.html inline
   script (M-04 CSP hardening). Depends on htmx (loaded in base.html head). */

function editorScrollToValidationIssues() {
  var sidebar = document.getElementById('editor-sidebar');
  var panel = document.getElementById('validation-issues-panel');
  if (sidebar) {
    sidebar.scrollTop = 0;
  }
  if (panel) {
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  var wrap = document.getElementById('side-panel-validation');
  if (wrap) {
    wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function editorOpenAddNode() {
  var panel = document.getElementById('editor-add-node-panel');
  if (!panel) return;
  var details = panel.querySelector('details');
  if (details) details.open = true;
  var sidebar = document.getElementById('editor-sidebar');
  if (sidebar) {
    sidebar.scrollTop = 0;
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function editorSelectGraphNode(nodeElement) {
  var graph = nodeElement.closest('.dt-graph');
  if (!graph) return;
  if (graph.dataset.readOnly === 'true') {
    alert('This assessment is public and cannot be edited directly. Create a new version to make changes.');
    return;
  }

  var form = document.createElement('form');
  form.method = 'POST';
  form.action = '/decision-trees/editor/select_node_with_decision_tree';
  form.setAttribute('hx-post', form.action);
  form.setAttribute('hx-target', '#side-panel-content');
  form.setAttribute('hx-swap', 'innerHTML');

  var values = {
    node_id: nodeElement.dataset.nodeId,
    decision_tree_id: graph.dataset.decisionTreeId,
  };
  Object.keys(values).forEach(function(name) {
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = name;
    input.value = values[name] || '';
    form.appendChild(input);
  });

  document.body.appendChild(form);
  htmx.process(form);
  form.requestSubmit();
}

document.addEventListener('click', function(event) {
  var node = event.target.closest && event.target.closest('.dt-graph .node[data-node-id]');
  if (node) editorSelectGraphNode(node);
});

document.addEventListener('keydown', function(event) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  var node = event.target.closest && event.target.closest('.dt-graph .node[data-node-id]');
  if (!node) return;
  event.preventDefault();
  editorSelectGraphNode(node);
});

// Buttons that call the global helpers above via data-action (CSP: no inline onclick).
document.body.addEventListener('click', function (event) {
  if (event.target.closest('[data-action="editor-scroll-to-validation-issues"]')) {
    editorScrollToValidationIssues();
  }
  if (event.target.closest('[data-action="editor-open-add-node"]')) {
    editorOpenAddNode();
  }
});

/** Client-side view switch (matches server ?view= without full reload). */
function editorShowView(view) {
  var panes = {
    graph: document.getElementById('view-graph'),
    checklist: document.getElementById('view-checklist'),
    lexicon: document.getElementById('view-lexicon'),
    tools: document.getElementById('view-tools'),
  };
  Object.keys(panes).forEach(function (name) {
    var pane = panes[name];
    if (pane) pane.hidden = name !== view;
  });
  var tabs = {
    graph: document.getElementById('tab-graph'),
    checklist: document.getElementById('tab-checklist'),
    lexicon: document.getElementById('tab-lexicon'),
    tools: document.getElementById('tab-tools'),
  };
  var tablist = document.querySelector('[role="tablist"][aria-label="Editor views"]');
  var activeClass = tablist && tablist.dataset.tabActiveClass;
  var inactiveClass = tablist && tablist.dataset.tabInactiveClass;
  Object.keys(tabs).forEach(function (name) {
    var tab = tabs[name];
    if (!tab) return;
    var isActive = name === view;
    tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
    if (activeClass && inactiveClass) {
      tab.className = isActive ? activeClass : inactiveClass;
    }
  });
}

// Resizable sidebar — width persisted in cookie (server renders initial width)
(function() {
  const COOKIE_NAME = 'smeme_editor_sidebar_width';
  const LEGACY_KEY = 'editor-sidebar-width';
  let isResizing = false;
  let startX = 0;
  let startWidth = 0;

  function persistSidebarWidth(width) {
    const clamped = Math.max(280, Math.min(800, Math.round(width)));
    document.cookie = COOKIE_NAME + '=' + clamped + '; path=/; max-age=31536000; samesite=lax';
    try { localStorage.removeItem(LEGACY_KEY); } catch (e) {}
  }

  try {
    const legacy = localStorage.getItem(LEGACY_KEY);
    if (legacy && !document.cookie.split(';').some(function (c) { return c.trim().startsWith(COOKIE_NAME + '='); })) {
      persistSidebarWidth(parseInt(legacy, 10));
    }
  } catch (e) {}

  document.addEventListener('mousedown', (e) => {
    if (!e.target.closest('#editor-divider')) return;

    const sidebarEl = document.getElementById('editor-sidebar');
    if (!sidebarEl) return;

    isResizing = true;
    startX = e.clientX;
    startWidth = sidebarEl.offsetWidth;
    document.body.classList.add('resizing-editor');
    e.preventDefault();
  });

  document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;

    const sidebarEl = document.getElementById('editor-sidebar');
    if (!sidebarEl) return;

    const diff = startX - e.clientX;
    sidebarEl.style.width = Math.max(280, Math.min(800, startWidth + diff)) + 'px';
  });

  document.addEventListener('mouseup', () => {
    if (!isResizing) return;

    const sidebarEl = document.getElementById('editor-sidebar');
    if (sidebarEl) {
      persistSidebarWidth(sidebarEl.offsetWidth);
    }

    isResizing = false;
    document.body.classList.remove('resizing-editor');
  });
})();

// Graph zoom — fixed viewBox, scaled presentation width/height (see _graph_zoom_controls.html)
(function () {
  var MIN_ZOOM = 0.25;
  var MAX_ZOOM = 2;
  var ZOOM_STEP = 1.2;
  var DEFAULT_ZOOM = 1;
  var FIT_PAD = 32;

  var GRAPH_ZOOM_PATH = /\/decision_tree\/editor\/(select_node|create_node|update_node|delete_node|create_edge|update_edge|delete_edge|create_node_wired)/;

  function graphPane() {
    return document.getElementById('view-graph');
  }

  function graphSvg() {
    var pane = graphPane();
    return pane && pane.querySelector('#graph-scroll-body .dt-graph');
  }

  function storageKey() {
    var pane = graphPane();
    var id = pane && pane.dataset.decisionTreeId;
    return id ? 'smeme_graph_zoom:' + id : null;
  }

  function clampZoom(scale) {
    return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, scale));
  }

  function readZoom() {
    var key = storageKey();
    if (!key) return DEFAULT_ZOOM;
    try {
      var stored = parseFloat(sessionStorage.getItem(key));
      return isFinite(stored) ? clampZoom(stored) : DEFAULT_ZOOM;
    } catch (e) {
      return DEFAULT_ZOOM;
    }
  }

  function writeZoom(scale) {
    var key = storageKey();
    if (!key) return;
    try { sessionStorage.setItem(key, String(scale)); } catch (e) {}
  }

  function updateZoomLabel(scale) {
    var pane = graphPane();
    if (!pane) return;
    var label = pane.querySelector('[data-graph-zoom-label]');
    if (label) label.textContent = Math.round(scale * 100) + '%';
  }

  function applyGraphZoom(scale, opts) {
    opts = opts || {};
    scale = clampZoom(scale);
    var svg = graphSvg();
    if (!svg) return scale;
    var baseW = parseFloat(svg.dataset.graphWidth);
    var baseH = parseFloat(svg.dataset.graphHeight);
    if (!baseW || !baseH) return scale;
    svg.style.width = (baseW * scale) + 'px';
    svg.style.height = (baseH * scale) + 'px';
    if (!opts.skipPersist) writeZoom(scale);
    updateZoomLabel(scale);
    return scale;
  }

  function zoomAt(clientX, clientY, newScale) {
    var pane = graphPane();
    if (!pane || pane.hidden) return applyGraphZoom(newScale);

    var oldZoom = readZoom();
    newScale = clampZoom(newScale);
    if (oldZoom === newScale) return newScale;

    var rect = pane.getBoundingClientRect();
    var x = pane.scrollLeft + (clientX - rect.left);
    var y = pane.scrollTop + (clientY - rect.top);
    var ratio = newScale / oldZoom;

    applyGraphZoom(newScale);

    pane.scrollLeft = x * ratio - (clientX - rect.left);
    pane.scrollTop = y * ratio - (clientY - rect.top);
    return newScale;
  }

  function fitGraphToPane() {
    var pane = graphPane();
    var svg = graphSvg();
    if (!pane || !svg || pane.hidden || pane.clientWidth === 0 || pane.clientHeight === 0) return;
    var baseW = parseFloat(svg.dataset.graphWidth);
    var baseH = parseFloat(svg.dataset.graphHeight);
    if (!baseW || !baseH) return;
    var scale = Math.min(
      (pane.clientWidth - FIT_PAD) / baseW,
      (pane.clientHeight - FIT_PAD) / baseH,
      1
    );
    applyGraphZoom(clampZoom(scale));
    pane.scrollTop = 0;
    pane.scrollLeft = 0;
  }

  function isGraphZoomRelevantSettle(evt) {
    if (!graphPane()) return false;
    var target = evt.detail.target;
    if (target && target.id === 'view-graph') return true;
    var path = (evt.detail.pathInfo && evt.detail.pathInfo.requestPath) || '';
    if (!path || !GRAPH_ZOOM_PATH.test(path)) return false;
    return !!graphSvg();
  }

  window.editorGraphZoom = {
    reapply: function () {
      return applyGraphZoom(readZoom(), { skipPersist: true });
    },
    step: function (direction, clientX, clientY) {
      var next = direction > 0 ? readZoom() * ZOOM_STEP : readZoom() / ZOOM_STEP;
      if (clientX != null && clientY != null) {
        return zoomAt(clientX, clientY, next);
      }
      return applyGraphZoom(next);
    },
    reset: function () { return applyGraphZoom(DEFAULT_ZOOM); },
    fit: fitGraphToPane,
    isRelevantSettle: isGraphZoomRelevantSettle,
  };

  function initGraphZoom() {
    if (graphSvg()) window.editorGraphZoom.reapply();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGraphZoom);
  } else {
    initGraphZoom();
  }

  document.body.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-graph-zoom]');
    if (!btn || !btn.closest('#view-graph')) return;
    var action = btn.getAttribute('data-graph-zoom');
    if (action === 'in') window.editorGraphZoom.step(1);
    else if (action === 'out') window.editorGraphZoom.step(-1);
    else if (action === 'reset') window.editorGraphZoom.reset();
    else if (action === 'fit') window.editorGraphZoom.fit();
  });

  document.body.addEventListener('wheel', function (e) {
    var pane = graphPane();
    if (!pane || pane.hidden || !pane.contains(e.target)) return;
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    window.editorGraphZoom.step(e.deltaY < 0 ? 1 : -1, e.clientX, e.clientY);
  }, { passive: false });

  document.addEventListener('keydown', function (e) {
    var pane = graphPane();
    if (!pane || pane.hidden) return;
    if ((e.ctrlKey || e.metaKey) && e.key === '0') {
      e.preventDefault();
      window.editorGraphZoom.reset();
    }
  });
})();

// After node selection: keep checklist on the selected card and show node attributes in the sidebar.
(function () {
  function scrollWithin(container, child) {
    if (!container || !child) return;
    var containerRect = container.getBoundingClientRect();
    var childRect = child.getBoundingClientRect();
    if (childRect.top < containerRect.top) {
      container.scrollTop -= containerRect.top - childRect.top;
    } else if (childRect.bottom > containerRect.bottom) {
      container.scrollTop += childRect.bottom - containerRect.bottom;
    }
  }

  function scrollToTop(container, child, padding) {
    if (!container || !child) return;
    var containerRect = container.getBoundingClientRect();
    var childRect = child.getBoundingClientRect();
    container.scrollTop += childRect.top - containerRect.top - (padding || 0);
  }

  document.body.addEventListener('htmx:afterSettle', function (evt) {
    if (window.editorGraphZoom && window.editorGraphZoom.isRelevantSettle(evt)) {
      window.editorGraphZoom.reapply();
    }

    var path = evt.detail.pathInfo && evt.detail.pathInfo.requestPath;
    if (!path || path.indexOf('select_node') === -1) return;

    var trigger = evt.detail.elt;
    var nodeId = null;
    var fromValidationJump = false;
    if (trigger) {
      var form = trigger.closest('form');
      if (form) {
        var nodeInput = form.querySelector('input[name="node_id"]');
        if (nodeInput) nodeId = nodeInput.value;
        fromValidationJump = form.hasAttribute('data-validation-jump');
      }
    }

    if (fromValidationJump && nodeId) {
      editorShowView('graph');
    }

    var checklist = document.getElementById('view-checklist');
    if (checklist && !checklist.hidden) {
      var card = nodeId ? document.getElementById('checklist-card-' + nodeId) : null;
      scrollWithin(checklist, card || checklist.querySelector('.question-card.ring-2'));
    }

    var graphPane = document.getElementById('view-graph');
    if (graphPane && !graphPane.hidden && nodeId) {
      scrollWithin(graphPane, graphPane.querySelector('[data-node-id="' + nodeId + '"]'));
    }

    var sidebar = document.getElementById('editor-sidebar');
    if (!sidebar) return;

    var anchor = document.getElementById('node-editor-form')
      || document.querySelector('#side-panel-content .side-panel-header');
    if (anchor) {
      scrollToTop(sidebar, anchor, 8);
    } else {
      sidebar.scrollTop = 0;
    }
  });
})();
