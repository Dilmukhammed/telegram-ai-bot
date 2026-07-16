#!/usr/bin/env python3
"""Interactive graph lab: type facts, watch one user graph grow.

Requires network/LLM (same keys as the bot). Default-off memory flags are
forced on for this process only: extract→verify→resolve(PR7+PR11 ER)→graph,
PR8 shadow retrieval, PR12 summaries+communities (no prompt inject).

  python scripts/graph_lab.py
  open http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("graph_lab")

DEMO_USER_ID = 1
INDEX_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Memory Graph Lab</title>
  <style>
    :root {
      --bg: #0f1419;
      --panel: #1a222c;
      --line: #2c3848;
      --text: #e7eef7;
      --muted: #8b9bb0;
      --accent: #3d9cfd;
      --ok: #3ecf8e;
      --warn: #f0b429;
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
    }
    body {
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      position: fixed;
      inset: 0;
      display: grid;
      grid-template-columns: 360px 1fr;
      grid-template-rows: 100%;
    }
    aside {
      border-right: 1px solid var(--line);
      background: var(--panel);
      display: flex;
      flex-direction: column;
      min-height: 0;
      overflow: hidden;
    }
    header {
      flex: 0 0 auto;
      padding: 14px 16px 10px;
      border-bottom: 1px solid var(--line);
    }
    header h1 {
      margin: 0 0 4px;
      font-size: 17px;
      font-weight: 650;
    }
    header p {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }
    #log {
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 12px 14px;
      font-size: 13px;
      overflow-x: auto;
      white-space: nowrap;
      line-height: 1.4;
    }
    .msg {
      margin: 0 0 8px;
      padding: 9px 11px;
      border-radius: 10px;
      background: #121820;
      border: 1px solid var(--line);
      white-space: pre-wrap;
      word-break: break-word;
    }
    .msg .meta { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
    .msg.sys { border-color: #35507a; }
    .msg.err { border-color: #8b3a3a; color: #ffb4b4; }
    form {
      flex: 0 0 auto;
      display: grid;
      gap: 8px;
      padding: 10px 14px 14px;
      border-top: 1px solid var(--line);
    }
    textarea {
      width: 100%;
      height: 78px;
      max-height: 78px;
      resize: none;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: #0f1419;
      color: var(--text);
      padding: 10px 12px;
      font: inherit;
    }
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    button {
      border: 0;
      border-radius: 10px;
      padding: 9px 12px;
      font: inherit;
      cursor: pointer;
      background: var(--accent);
      color: #041018;
      font-weight: 650;
    }
    button.secondary {
      background: #243041;
      color: var(--text);
      font-weight: 500;
    }
    button:disabled { opacity: 0.5; cursor: wait; }
    main {
      position: relative;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
    }
    .toolbar {
      position: absolute;
      z-index: 2;
      left: 0; right: 0; top: 0;
      display: flex;
      gap: 12px;
      align-items: center;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: rgba(15,20,25,0.92);
      color: var(--muted);
      font-size: 13px;
    }
    .toolbar strong { color: var(--text); }
    .legend { margin-left: auto; font-size: 12px; }
    .legend .solid { color: #9fb3c8; }
    .legend .dash { color: #f0b429; }
    .legend .hist { color: #7a8494; }
    .stack {
      position: absolute;
      z-index: 2;
      left: 0; right: 0; top: 42px;
      padding: 6px 14px;
      border-bottom: 1px solid var(--line);
      background: rgba(15,20,25,0.88);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
      max-height: 56px;
      overflow: hidden;
    }
    #attachmentTrace {
      top: 98px;
      height: 172px;
      max-height: 172px;
      color: #b8c7da;
      background: rgba(17,25,34,0.94);
      white-space: pre-wrap;
      overflow: auto;
    }
    #graph {
      position: absolute;
      inset: 0;
      top: 270px;
      overflow: hidden;
      background:
        radial-gradient(circle at 20% 20%, #152033 0, transparent 40%),
        radial-gradient(circle at 80% 80%, #12281f 0, transparent 35%),
        var(--bg);
    }
  </style>
</head>
<body>
  <aside>
    <header>
      <h1>Memory Graph Lab</h1>
      <p>Пиши факты. Pipeline: extract→verify→resolve(<strong>PR7/11</strong>)→graph → <strong>PR8 shadow</strong> → <strong>PR12 summaries</strong> → <strong>PR14 v2 + ReAct research</strong>. Prompt не мутируется.</p>
    </header>
    <div id="log"></div>
    <form id="form">
      <textarea id="text" placeholder="Например: Я люблю Kartoffelsalat.&#10;Я люблю итальянскую еду."></textarea>
      <div class="row">
        <button type="submit" id="send">Добавить в память</button>
        <button type="button" class="secondary" id="refresh">Обновить граф</button>
        <button type="button" class="secondary" id="shadow">Shadow</button>
        <button type="button" class="secondary" id="attach">Attach</button>
        <button type="button" class="secondary" id="clear">Очистить</button>
      </div>
    </form>
  </aside>
  <main>
    <div class="toolbar">
      <span>durable: <strong id="nEdges">0</strong></span>
      <span>deferred: <strong id="nDeferred">0</strong></span>
      <span>historical: <strong id="nHistorical">0</strong></span>
      <span>nodes: <strong id="nNodes">0</strong></span>
      <span>revision: <strong id="rev">0</strong></span>
      <span>policy: <strong id="policy">—</strong></span>
      <span>summaries: <strong id="nSummaries">0</strong></span>
      <span>communities: <strong id="nCommunities">0</strong></span>
      <span>dirty: <strong id="nDirty">0</strong></span>
      <span>attach: <strong id="nAttachEvents">0</strong></span>
      <span>reverted: <strong id="nAttachReverted">0</strong></span>
      <span>constraints: <strong id="nAttachConstraints">0</strong></span>
      <span>dependencies: <strong id="nAttachDependencies">0</strong></span>
      <span>attach_dirty: <strong id="nAttachDirty">0</strong></span>
      <span>merges: <strong id="nMerges">0</strong></span>
      <span>shadow: <strong id="nShadow">0</strong></span>
      <span id="status">idle</span>
      <span class="legend"><span class="solid">━ durable</span> · <span class="dash">┅ deferred</span> · <span class="hist">╌ historical</span> · <span style="color:#ff6b7a">¬ negative</span> · <span style="color:#5ec8ff">━ attach</span></span>
    </div>
    <div id="stack" class="stack">stack idle</div>
    <div id="attachmentTrace" class="stack">PR14 v2 + ReAct trace idle</div>
    <div id="graph"></div>
  </main>
  <script>
    /*
     * Small dependency-free graph renderer for Graph Lab.
     * The page must also work in offline/local environments where loading
     * vis-network from a public CDN is not possible.
     */
    class GraphDataSet {
      constructor(items=[]) { this.items = []; this.add(items); }
      clear() { this.items = []; }
      add(items) { this.items.push(...(Array.isArray(items) ? items : [items])); }
    }

    class GraphNetwork {
      constructor(container, data) {
        this.container = container;
        this.data = data;
        this.resizeObserver = new ResizeObserver(() => this.render());
        this.resizeObserver.observe(container);
        this.render();
      }
      setData(data) { this.data = data; this.render(); }
      setSize() { this.render(); }
      stabilize() {}
      fit() { this.render(); }
      render() {
        const nodeItems = this.data?.nodes?.items || [];
        const edgeItems = this.data?.edges?.items || [];
        const width = Math.max(this.container.clientWidth, 320);
        const height = Math.max(this.container.clientHeight, 260);
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
        svg.setAttribute("width", "100%");
        svg.setAttribute("height", "100%");
        svg.style.display = "block";

        const defs = document.createElementNS(ns, "defs");
        const marker = document.createElementNS(ns, "marker");
        marker.setAttribute("id", "graph-arrow");
        marker.setAttribute("viewBox", "0 0 10 10");
        marker.setAttribute("refX", "9");
        marker.setAttribute("refY", "5");
        marker.setAttribute("markerWidth", "6");
        marker.setAttribute("markerHeight", "6");
        marker.setAttribute("orient", "auto-start-reverse");
        const arrow = document.createElementNS(ns, "path");
        arrow.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
        arrow.setAttribute("fill", "#6b7c93");
        marker.appendChild(arrow);
        defs.appendChild(marker);
        svg.appendChild(defs);

        const positions = new Map();
        const selfIndex = nodeItems.findIndex(n => n.label === "self");
        const ordered = selfIndex > 0
          ? [nodeItems[selfIndex], ...nodeItems.filter((_, i) => i !== selfIndex)]
          : nodeItems;
        const cx = width / 2;
        const cy = height / 2;
        const others = Math.max(ordered.length - 1, 1);
        ordered.forEach((node, index) => {
          if (index === 0 && (node.label === "self" || ordered.length === 1)) {
            positions.set(node.id, { x: cx, y: cy });
            return;
          }
          const ringIndex = node.label === "self" ? index : index - (ordered[0]?.label === "self" ? 1 : 0);
          const ring = Math.floor(Math.max(ringIndex, 0) / 12);
          const slot = Math.max(ringIndex, 0) % 12;
          const ringCount = Math.min(12, others - ring * 12);
          const angle = ((2 * Math.PI * slot) / Math.max(ringCount, 1)) - Math.PI / 2;
          const radius = Math.min(width, height) * (0.28 + ring * 0.16);
          positions.set(node.id, {
            x: cx + Math.cos(angle) * radius,
            y: cy + Math.sin(angle) * radius,
          });
        });

        edgeItems.forEach(edge => {
          const from = positions.get(edge.from);
          const to = positions.get(edge.to);
          if (!from || !to) return;
          const line = document.createElementNS(ns, "line");
          line.setAttribute("x1", String(from.x));
          line.setAttribute("y1", String(from.y));
          line.setAttribute("x2", String(to.x));
          line.setAttribute("y2", String(to.y));
          line.setAttribute("stroke", edge.color?.color || "#6b7c93");
          line.setAttribute("stroke-width", String(edge.width || 2));
          line.setAttribute("marker-end", "url(#graph-arrow)");
          if (edge.dashes) line.setAttribute("stroke-dasharray", "7 5");
          const title = document.createElementNS(ns, "title");
          title.textContent = edge.title || edge.label || "";
          line.appendChild(title);
          svg.appendChild(line);

          const label = document.createElementNS(ns, "text");
          label.setAttribute("x", String((from.x + to.x) / 2));
          label.setAttribute("y", String((from.y + to.y) / 2 - 7));
          label.setAttribute("fill", edge.font?.color || "#a9b7c9");
          label.setAttribute("font-size", String(edge.font?.size || 11));
          label.setAttribute("text-anchor", "middle");
          label.setAttribute("paint-order", "stroke");
          label.setAttribute("stroke", "#0f1419");
          label.setAttribute("stroke-width", "4");
          label.textContent = edge.label || "";
          svg.appendChild(label);
        });

        ordered.forEach(node => {
          const pos = positions.get(node.id);
          if (!pos) return;
          const group = document.createElementNS(ns, "g");
          group.style.opacity = String(node.opacity ?? 1);
          const labelText = node.label || node.id;
          const radius = Math.max(30, Math.min(70, 18 + labelText.length * 3.2));
          const circle = document.createElementNS(ns, "ellipse");
          circle.setAttribute("cx", String(pos.x));
          circle.setAttribute("cy", String(pos.y));
          circle.setAttribute("rx", String(radius));
          circle.setAttribute("ry", "25");
          circle.setAttribute("fill", node.color?.background || "#3a2f55");
          circle.setAttribute("stroke", node.color?.border || "#b48eff");
          circle.setAttribute("stroke-width", String(node.color?.borderWidth || 2));
          const title = document.createElementNS(ns, "title");
          title.textContent = node.title || labelText;
          circle.appendChild(title);
          group.appendChild(circle);
          const text = document.createElementNS(ns, "text");
          text.setAttribute("x", String(pos.x));
          text.setAttribute("y", String(pos.y + 4));
          text.setAttribute("fill", node.font?.color || "#e7eef7");
          text.setAttribute("font-size", "13");
          text.setAttribute("font-weight", node.label === "self" ? "700" : "500");
          text.setAttribute("text-anchor", "middle");
          text.textContent = labelText.length > 22 ? labelText.slice(0, 20) + "…" : labelText;
          group.appendChild(text);
          svg.appendChild(group);
        });

        this.container.replaceChildren(svg);
      }
    }

    const vis = { DataSet: GraphDataSet, Network: GraphNetwork };
    const logEl = document.getElementById("log");
    const statusEl = document.getElementById("status");
    const sendBtn = document.getElementById("send");
    const stackEl = document.getElementById("stack");
    const attachmentTraceEl = document.getElementById("attachmentTrace");
    let network = null;
    let nodes = new vis.DataSet([]);
    let edges = new vis.DataSet([]);
    let lastQuery = "";
    let lastBeliefId = "";
    let pollTimer = null;

    function addLog(text, kind="user") {
      const div = document.createElement("div");
      div.className = "msg " + kind;
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = new Date().toLocaleTimeString();
      div.appendChild(meta);
      div.appendChild(document.createTextNode(text));
      logEl.prepend(div);
    }

    function paint(graph) {
      if (!graph) return;
      const nodeItems = (graph.nodes || []).map(n => {
        const deferred = !!n.deferred;
        const historical = !!n.historical;
        const isSelf = n.label === "self" || (n.properties||{}).identity_key === "root_user";
        let color;
        if (n.node_type === "concept") {
          color = historical
            ? { background: "#1a1f26", border: "#5a6573", borderWidth: 1 }
            : deferred
            ? { background: "#2a4034", border: "#f0b429", borderWidth: 2 }
            : { background: "#1f6f54", border: "#3ecf8e" };
        } else if (isSelf) {
          color = { background: "#3d5a80", border: "#3d9cfd" };
        } else {
          color = historical
            ? { background: "#1a1f26", border: "#5a6573", borderWidth: 1 }
            : deferred
            ? { background: "#3a3420", border: "#f0b429", borderWidth: 2 }
            : { background: "#3a2f55", border: "#b48eff" };
        }
        const tag = historical ? " [historical]" : deferred ? " [deferred]" : "";
        return {
          id: n.id,
          label: n.label || n.id,
          title: `${n.node_type}${tag}\\n${n.id}`,
          group: n.node_type || "entity",
          color,
          font: { color: historical ? "#8b9bb0" : "#e7eef7" },
          opacity: historical ? 0.55 : deferred ? 0.85 : 1,
        };
      });
      const edgeItems = (graph.edges || []).map(e => {
        const deferred = !!e.deferred;
        const historical = !!e.historical;
        const attach = !!(e.attach || (e.edge_type || "").startsWith("attach:"));
        const negative = e.polarity === "negative";
        return {
          id: e.id,
          from: e.from,
          to: e.to,
          label: negative
            ? `¬ ${e.edge_type}`
            : historical
            ? `${e.edge_type} ∎`
            : deferred
            ? `${e.edge_type} ?`
            : e.edge_type,
          arrows: "to",
          dashes: deferred || historical || negative,
          width: attach ? 2.5 : historical ? 1 : deferred ? 1.5 : 2,
          color: negative
            ? { color: "#ff6b7a", highlight: "#ff9aa5" }
            : attach
            ? { color: "#5ec8ff", highlight: "#9adcff" }
            : historical
            ? { color: "#5a6573", highlight: "#8b9bb0" }
            : deferred
            ? { color: "#f0b429", highlight: "#ffd666" }
            : { color: "#6b7c93", highlight: "#3d9cfd" },
          font: {
            color: negative ? "#ff6b7a" : attach ? "#5ec8ff" : historical ? "#7a8494" : deferred ? "#f0b429" : "#a9b7c9",
            size: 11,
            strokeWidth: 0,
          },
          title: negative
            ? `${e.belief_id}\n explicit negative belief (not a positive preference)`
            : attach
            ? `${e.belief_id || e.id}\\n event=${e.attachment_event_id || "overlay"} · ${e.utility_class || ""} · ${e.attachment_tier || ""} · v${e.attachment_version || "?"}`
            : historical
            ? `${e.belief_id}\\n historical (PR7 superseded)`
            : deferred
            ? `${e.belief_id}\\n deferred: ${(e.reasons||[]).join(", ")}`
            : e.belief_id,
        };
      });
      nodes.clear(); edges.clear();
      nodes.add(nodeItems); edges.add(edgeItems);
      const durable = edgeItems.filter(e => !e.dashes).length;
      const deferredN = edgeItems.filter(e => e.dashes && (graph.edges||[]).find(x => x.id===e.id && x.deferred)).length;
      const historicalN = edgeItems.filter(e => (graph.edges||[]).find(x => x.id===e.id && x.historical)).length;
      document.getElementById("nNodes").textContent = nodeItems.length;
      document.getElementById("nEdges").textContent = durable;
      document.getElementById("nDeferred").textContent = deferredN;
      document.getElementById("nHistorical").textContent = historicalN;
      document.getElementById("rev").textContent = graph.revision ?? 0;
      document.getElementById("policy").textContent = graph.policy || "—";
      const box = document.getElementById("graph");
      if (!network) {
        network = new vis.Network(
          box,
          { nodes, edges },
          {
            autoResize: true,
            height: "100%",
            width: "100%",
            physics: {
              solver: "forceAtlas2Based",
              forceAtlas2Based: { gravitationalConstant: -36, springLength: 110 },
              stabilization: { iterations: 60 },
            },
            interaction: { hover: true, tooltipDelay: 120, zoomView: true },
            edges: { smooth: { type: "dynamic" } },
          }
        );
      } else {
        network.setData({ nodes, edges });
        network.setSize(box.clientWidth + "px", box.clientHeight + "px");
        network.stabilize(20);
        network.fit({ animation: false });
      }
    }

    function stopPoll() {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    function startPoll() {
      stopPoll();
      pollTimer = setInterval(async () => {
        try {
          const res = await fetch("/api/graph");
          const data = await res.json();
          paint(data);
          const stackData = await loadStackData();
          updateStack(stackData.status, stackData.summaries, null, stackData.attach);
        } catch (_) { /* ignore transient poll errors */ }
      }, 900);
    }

    function updateCounters(status) {
      if (!status) return;
      document.getElementById("nSummaries").textContent = status.summaries_active ?? 0;
      document.getElementById("nCommunities").textContent = status.communities ?? 0;
      document.getElementById("nDirty").textContent = status.dirty ?? 0;
      document.getElementById("nAttachEvents").textContent = status.attach_events ?? 0;
      document.getElementById("nAttachReverted").textContent = status.attach_reverted ?? 0;
      document.getElementById("nAttachConstraints").textContent = status.attach_constraints ?? 0;
      document.getElementById("nAttachDependencies").textContent = status.attach_dependencies ?? 0;
      document.getElementById("nAttachDirty").textContent = status.attach_dirty ?? 0;
      document.getElementById("nMerges").textContent = status.merge_events ?? 0;
      document.getElementById("nShadow").textContent = status.shadow_runs ?? 0;
    }

    function updateStack(status, summaries, shadow, attachEvents) {
      const parts = [];
      if (shadow && !shadow.error) {
        parts.push(
          `shadow: ${shadow.belief_count ?? 0} beliefs ~${shadow.token_estimate ?? 0} tok` +
          (shadow.core_profile_present ? " | core✓" : "") +
          (shadow.active_state_present ? " | state✓" : "")
        );
        if (shadow.core_profile_line) parts.push(`core: ${shadow.core_profile_line}`);
        if (shadow.active_state_line) parts.push(`state: ${shadow.active_state_line}`);
      } else if (shadow && shadow.error) {
        parts.push(`shadow error: ${shadow.error}`);
      }
      if (status) {
        parts.push(
          `summaries=${status.summaries_active ?? 0} communities=${status.communities ?? 0} ` +
          `dirty=${status.dirty ?? 0} attach=${status.attach_events ?? 0} ` +
          `attach_dirty=${status.attach_dirty ?? 0} merges=${status.merge_events ?? 0}`
        );
      }
      if (summaries && summaries.summaries && summaries.summaries.length) {
        const top = summaries.summaries.slice(0, 3).map(s => `${s.summary_type}:${(s.content_preview||"").slice(0,40)}`);
        parts.push(`active: ${top.join(" | ")}`);
      }
      const events = (attachEvents && attachEvents.events) || attachEvents || [];
      if (events.length) {
        const topA = events.slice(0, 4).map(e => `${e.op}:${e.status}:${(e.utility_class||"")}`);
        parts.push(`attach: ${topA.join(" | ")}`);
      }
      const constraints = (attachEvents && attachEvents.constraints) || [];
      if (constraints.length) {
        parts.push(`constraints: ${constraints.slice(0,3).map(c => `${c.constraint_type}→${c.target_label || c.target_entity_id}`).join(" | ")}`);
      }
      stackEl.textContent = parts.length ? parts.join(" · ") : "stack idle";
    }

    function renderAttachmentTrace(data) {
      if (!data) { attachmentTraceEl.textContent = "PR14 v2 + ReAct trace idle"; return; }
      const accepted = data.accepted_hypotheses || [];
      const shortlist = data.shortlist || [];
      const layers = data.layer_trace || [];
      const research = data.research || null;
      const lines = [
        `PR14 v2 · accepted=${accepted.length} · candidates=${shortlist.length} · llm=${data.llm_calls ?? 0}`,
      ];
      if (accepted.length) lines.push(`set: ${accepted.map(h => `${h.op}→${h.target_label || h.target_id} (${Number(h.confidence || 0).toFixed(2)})`).join(" | ")}`);
      if (shortlist.length) lines.push(`hybrid: ${shortlist.slice(0,6).map(c => `${c.label}[${c.channel}:${Number(c.score || 0).toFixed(3)}]`).join(" | ")}`);
      if (layers.length) lines.push(`critics: ${layers.map(l => `${l.layer}:${l.verdict || "?"}`).join(" → ")}`);
      if (research) {
        const final = research.final || {};
        lines.push("");
        lines.push(
          `ReAct ${research.mode || "shadow"} · status=${research.status || "?"} ` +
          `decision=${final.decision || "?"} · tools=${(research.trace || []).length} ` +
          `llm=${research.llm_calls ?? 0} · revision=${research.graph_revision_before ?? "?"}` +
          (research.stale ? " · STALE" : "")
        );
        if (research.report_markdown) lines.push(`agent report: ${research.report_markdown}`);
        for (const step of (research.trace || [])) {
          const result = step.result || {};
          const count = (result.hits || result.paths || result.events || []).length || 0;
          lines.push(
            `[step ${step.step_id}] ${step.tool} ${JSON.stringify(step.arguments || {})}` +
            ` → ${result.error ? "ERROR " + result.error : count + " results"}`
          );
        }
        const confirmed = final.confirmed_existing || [];
        if (confirmed.length) {
          lines.push(`confirmed: ${confirmed.map(x => `${x.relation}→${x.target_id}`).join(" | ")}`);
        }
        const recommendations = final.recommendations || [];
        if (recommendations.length) {
          lines.push(`candidates: ${recommendations.map(x => `${x.op}→${x.target_id}`).join(" | ")}`);
        }
        if (research.error) lines.push(`research error: ${research.error}`);
        if (research.report_error) lines.push(`report error: ${research.report_error}`);
      }
      attachmentTraceEl.textContent = lines.join("\\n");
    }

    async function loadStackData() {
      const [statusRes, summariesRes, attachRes] = await Promise.all([
        fetch("/api/status"),
        fetch("/api/summaries"),
        fetch("/api/attach/events"),
      ]);
      const status = await statusRes.json();
      const summaries = await summariesRes.json();
      const attach = await attachRes.json();
      updateCounters(status);
      return { status, summaries, attach };
    }

    async function refresh() {
      const [graphRes, stackData] = await Promise.all([
        fetch("/api/graph"),
        loadStackData(),
      ]);
      const data = await graphRes.json();
      paint(data);
      updateStack(stackData.status, stackData.summaries, null, stackData.attach);
    }

    async function runAttach(beliefId) {
      const id = (beliefId || lastBeliefId || "").trim();
      if (!id) {
        addLog("no belief_id for attach dry-run (send a fact first)", "err");
        return;
      }
      statusEl.textContent = "attach…";
      try {
        const res = await fetch("/api/attach?belief_id=" + encodeURIComponent(id));
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        const accepted = data.accepted_hypotheses || [];
        const hyp = accepted.length
          ? accepted.map(h => `${h.op}→${h.target_label || h.target_id}`).join(" | ")
          : (data.hypothesis ? `${data.hypothesis.op}→${data.hypothesis.target_id}` : "none");
        addLog(
          `attach dry-run belief=${id} accepted=${data.accepted} ` +
          `abstain=${data.abstain_reason || "—"} hyp=${hyp} ` +
          `utility=${data.utility_class || "—"} llm=${data.llm_calls ?? 0} ` +
          `shortlist=${(data.shortlist||[]).length}`,
          "sys"
        );
        if (data.layer_trace && data.layer_trace.length) {
          addLog(
            "layers: " + data.layer_trace.map(l => `${l.layer}:${l.verdict || l.decision || "?"}`).join(" → "),
            "sys"
          );
        }
        renderAttachmentTrace(data);
        await refresh();
        statusEl.textContent = "idle";
      } catch (err) {
        addLog(String(err), "err");
        statusEl.textContent = "error";
      }
    }

    async function runShadow(text) {
      const q = (text || "").trim();
      if (!q) { addLog("no query for shadow", "err"); return; }
      statusEl.textContent = "shadow…";
      try {
        const res = await fetch("/api/shadow?q=" + encodeURIComponent(q));
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        const stackData = await loadStackData();
        updateStack(stackData.status, stackData.summaries, data, stackData.attach);
        addLog(
          `shadow: beliefs=${data.belief_count} tokens≈${data.token_estimate}` +
          (data.core_profile_present ? " core✓" : "") +
          (data.active_state_present ? " state✓" : ""),
          "sys"
        );
        statusEl.textContent = "idle";
      } catch (err) {
        addLog(String(err), "err");
        statusEl.textContent = "error";
      }
    }

    document.getElementById("form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const text = document.getElementById("text").value.trim();
      if (!text) return;
      sendBtn.disabled = true;
      statusEl.textContent = "processing…";
      lastQuery = text;
      addLog(text, "user");
      startPoll();
      try {
        const res = await fetch("/api/message", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        addLog(data.summary || "ok", "sys");
        if (data.latest_belief_id) lastBeliefId = data.latest_belief_id;
        paint(data.graph);
        updateCounters(data.status);
        updateStack(data.status, { summaries: data.summaries }, data.shadow, { events: data.attach_events || [] });
        if (data.attachment_research) {
          renderAttachmentTrace({
            accepted_hypotheses: [],
            shortlist: [],
            layer_trace: [],
            llm_calls: 0,
            research: data.attachment_research,
          });
        }
        document.getElementById("text").value = "";
        statusEl.textContent = "idle";
        // One more pull in case outbox/attach lagged a tick.
        await refresh();
      } catch (err) {
        addLog(String(err), "err");
        statusEl.textContent = "error";
        await refresh();
      } finally {
        stopPoll();
        sendBtn.disabled = false;
      }
    });

    document.getElementById("refresh").onclick = () => refresh();
    document.getElementById("shadow").onclick = () => {
      const text = document.getElementById("text").value.trim() || lastQuery;
      runShadow(text);
    };
    document.getElementById("attach").onclick = () => runAttach(lastBeliefId);
    document.getElementById("clear").onclick = async () => {
      if (!confirm("Стереть demo graph + chat для lab user?")) return;
      const res = await fetch("/api/reset", { method: "POST" });
      const data = await res.json();
      if (!res.ok) { addLog(data.error || "reset failed", "err"); return; }
      addLog("cleared", "sys");
      lastBeliefId = "";
      paint(data.graph);
      updateCounters(data.status);
      updateStack(data.status, { summaries: data.summaries }, null, null);
      renderAttachmentTrace(null);
    };

    refresh();
  </script>
</body>
</html>
"""


def _text_preview(text: str | None, *, limit: int = 160) -> str | None:
    if not text:
        return None
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _memory_status_dict(status: Any) -> dict[str, Any]:
    return {
        "schema_version": status.schema_version,
        "source_count": status.source_count,
        "active_version_count": status.active_version_count,
        "jobs_by_status": dict(status.jobs_by_status),
        "jobs_by_stage": dict(status.jobs_by_stage),
        "oldest_pending_age_seconds": status.oldest_pending_age_seconds,
        "active_worker_count": status.active_worker_count,
        "dead_job_count": status.dead_job_count,
        "active_mention_count": status.active_mention_count,
        "candidates_by_status": dict(status.candidates_by_status),
        "active_verdict_count": status.active_verdict_count,
        "active_candidate_score_count": status.active_candidate_score_count,
        "assertion_count": status.assertion_count,
        "belief_head_count": status.belief_head_count,
        "active_graph_edge_count": status.active_graph_edge_count,
        "summary_dirty_backlog": status.summary_dirty_backlog,
        "summaries_by_status": dict(status.summaries_by_status),
        "active_community_count": status.active_community_count,
        "attachment_dirty_backlog": status.attachment_dirty_backlog,
        "attachment_events_active": status.attachment_events_active,
    }


def _shadow_api_payload(result: Any, *, error: str | None = None) -> dict[str, Any]:
    if error:
        return {"error": error}
    pack = result.pack
    core = dict(pack.core_profile) if pack.core_profile else None
    active = dict(pack.active_state) if pack.active_state else None
    return {
        "run_id": result.run_id,
        "memory_needed": result.plan.memory_needed,
        "token_estimate": pack.token_estimate,
        "belief_count": len(pack.beliefs),
        "entity_count": len(pack.entities),
        "core_profile_present": core is not None,
        "active_state_present": active is not None,
        "core_profile_line": _text_preview(core.get("content") if core else None),
        "active_state_line": _text_preview(active.get("content") if active else None),
        "channels": {item.channel: len(item.hits) for item in result.channels},
    }


class GraphLab:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.data_dir = root / "data" / "graph_lab"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chat_path = self.data_dir / "chat.sqlite"
        self.tool_path = self.data_dir / "tool_results.sqlite"
        self.memory_path = self.data_dir / "memory.sqlite"
        self.service = None
        self.runtime = None
        self.chat_store = None
        self.verification_scheduler = None
        self.resolution_scheduler = None
        self.graph_scheduler = None
        self.summary_scheduler = None
        self.attachment_scheduler = None
        self.attachment_models: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self.session_id: str | None = None

    async def start(self) -> None:
        from bot.chat_store.store import ChatStore
        from bot.memory_chat_adapter import ChatEvidenceAdapter, set_text_ingest_sink
        from config import get_settings
        from llm import LLMClient
        from memory.config import MemoryConfig, er_config_from_memory_config
        from memory.extraction.pipeline import LLMExtractionModel, register_text_extractor
        from memory.graph.scheduler import GraphOutboxScheduler
        from memory.ingestion.runtime import TextIngestionRuntime
        from memory.resolution.critics import LLMLinkCriticModel
        from memory.resolution.pipeline import register_candidate_resolver
        from memory.resolution.scheduler import ResolutionScheduler
        from memory.service import MemoryService
        from memory.verification.pipeline import LLMVerificationModel, register_candidate_verifier
        from memory.verification.scheduler import VerificationScheduler
        from tools.tool_results.memory_adapter import ToolEvidenceAdapter
        from tools.tool_results.store import ToolResultStore

        settings = get_settings()
        config = MemoryConfig(
            ingest_enabled=True,
            db_path=str(self.memory_path),
            worker_enabled=True,
            worker_concurrency=2,
            worker_poll_seconds=0.05,
            job_lease_seconds=120,
            job_max_attempts=3,
            job_retry_base_seconds=0.5,
            job_retry_max_seconds=8.0,
            job_claim_batch_size=20,
            ingest_queue_maxsize=200,
            ingest_scan_interval_seconds=2.0,
            ingest_scan_batch_size=50,
            text_segment_chars=4000,
            text_segment_overlap=200,
            extraction_enabled=True,
            extraction_model_profile=settings.memory_extraction_model_profile,
            extraction_max_tokens=settings.memory_extraction_max_tokens,
            verification_enabled=True,
            verification_support_model_profile=settings.memory_verification_support_model_profile,
            verification_adversarial_model_profile=(
                settings.memory_verification_adversarial_model_profile
            ),
            verification_max_tokens=settings.memory_verification_max_tokens,
            verification_scan_interval_seconds=1.0,
            verification_scan_batch_size=50,
            verification_context_chars=settings.memory_verification_context_chars,
            verification_policy_version=settings.memory_verification_policy_version,
            resolution_enabled=True,
            resolution_scan_interval_seconds=1.0,
            resolution_scan_batch_size=50,
            required_verification_policy_version=(
                settings.memory_required_verification_policy_version
            ),
            resolution_link_support_model_profile=(
                settings.memory_resolution_link_support_model_profile
            ),
            resolution_link_adversarial_model_profile=(
                settings.memory_resolution_link_adversarial_model_profile
            ),
            resolution_max_tokens=settings.memory_resolution_max_tokens,
            graph_enabled=True,
            graph_scan_interval_seconds=0.5,
            graph_scan_batch_size=100,
            resolution_candidate_generation_enabled=True,
            resolution_fuzzy_blocking_enabled=True,
            resolution_fuzzy_min_trigram=0.6,
            resolution_cross_language_enabled=True,
            resolution_cluster_critic_enabled=True,
            resolution_merge_events_enabled=True,
            resolution_relink_on_invalidation=True,
            resolution_max_candidates=8,
            shadow_retrieval_enabled=True,
            shadow_retrieval_timeout_seconds=5.0,
            shadow_retrieval_token_budget=4000,
            shadow_retrieval_max_beliefs=24,
            shadow_retrieval_max_hops=3,
            documents_enabled=False,
            summaries_enabled=True,
            summaries_generation_enabled=True,
            summaries_verify_enabled=True,
            summaries_communities_enabled=True,
            summaries_shadow_pack_enabled=True,
            summaries_scan_interval_seconds=1.0,
            summaries_scan_batch_size=50,
            summaries_debounce_seconds=0.5,
            summaries_full_rebuild_every_n=20,
            summaries_model_profile=settings.memory_summaries_model_profile,
            summaries_verify_model_profile=settings.memory_summaries_verify_model_profile,
            summaries_max_tokens=settings.memory_summaries_max_tokens,
            summaries_community_label_enabled=False,
            attachment_enabled=True,
            attachment_generation_enabled=True,
            attachment_verify_enabled=True,
            attachment_two_generator_enabled=False,
            attachment_vector_enabled=True,
            attachment_curated_taxonomy_enabled=True,
            attachment_inferred_preference_enabled=True,
            attachment_write_graph_edges=True,
            attachment_write_possible_events=False,
            attachment_scan_interval_seconds=1.0,
            attachment_scan_batch_size=20,
            attachment_debounce_seconds=0.5,
            attachment_max_candidates=12,
            attachment_max_llm_calls=6,
            attachment_model_profile=settings.memory_attachment_model_profile,
            attachment_support_model_profile=settings.memory_attachment_support_model_profile,
            attachment_adversarial_model_profile=settings.memory_attachment_adversarial_model_profile,
            attachment_cluster_model_profile=settings.memory_attachment_cluster_model_profile,
            attachment_max_tokens=settings.memory_attachment_max_tokens,
            attachment_react_enabled=True,
            attachment_react_mode="shadow",
            attachment_react_model_profile=settings.memory_attachment_react_model_profile,
            attachment_react_max_actions=settings.memory_attachment_react_max_actions,
            attachment_react_max_hops=settings.memory_attachment_react_max_hops,
            attachment_react_max_results=settings.memory_attachment_react_max_results,
            attachment_react_max_nodes=settings.memory_attachment_react_max_nodes,
            attachment_react_max_tokens=settings.memory_attachment_react_max_tokens,
        )
        er_config = er_config_from_memory_config(config)

        self.chat_store = ChatStore(str(self.chat_path))
        tool_store = ToolResultStore(str(self.tool_path))
        self.service = MemoryService(config=config)
        chat_reader = ChatEvidenceAdapter(self.chat_store)
        tool_reader = ToolEvidenceAdapter(tool_store)
        self.runtime = TextIngestionRuntime(
            service=self.service,
            config=config,
            chat_reader=chat_reader,
            tool_reader=tool_reader,
        )

        register_text_extractor(
            self.service.registry,
            service=self.service,
            model=LLMExtractionModel(
                LLMClient(settings, profile=settings.memory_extraction_model_profile),
                model_profile=settings.memory_extraction_model_profile,
                max_tokens=settings.memory_extraction_max_tokens,
            ),
            timezone=settings.bot_timezone,
        )
        register_candidate_verifier(
            self.service.registry,
            service=self.service,
            support_model=LLMVerificationModel(
                LLMClient(settings, profile=settings.memory_verification_support_model_profile),
                model_profile=settings.memory_verification_support_model_profile,
                max_tokens=settings.memory_verification_max_tokens,
            ),
            adversarial_model=LLMVerificationModel(
                LLMClient(
                    settings,
                    profile=settings.memory_verification_adversarial_model_profile,
                ),
                model_profile=settings.memory_verification_adversarial_model_profile,
                max_tokens=settings.memory_verification_max_tokens,
            ),
            policy_version=settings.memory_verification_policy_version,
        )
        register_candidate_resolver(
            self.service.registry,
            service=self.service,
            required_verification_policy=settings.memory_required_verification_policy_version,
            support_model=LLMLinkCriticModel(
                LLMClient(settings, profile=settings.memory_resolution_link_support_model_profile),
                model_profile=settings.memory_resolution_link_support_model_profile,
                max_tokens=settings.memory_resolution_max_tokens,
            ),
            adversarial_model=LLMLinkCriticModel(
                LLMClient(
                    settings,
                    profile=settings.memory_resolution_link_adversarial_model_profile,
                ),
                model_profile=settings.memory_resolution_link_adversarial_model_profile,
                max_tokens=settings.memory_resolution_max_tokens,
            ),
            support_profile=settings.memory_resolution_link_support_model_profile,
            adversarial_profile=settings.memory_resolution_link_adversarial_model_profile,
            er_config=er_config,
        )

        from memory.summaries.generation.generator import LLMSummaryGeneratorModel
        from memory.summaries.processor import register_summary_generator
        from memory.summaries.scheduler import SummaryDirtyScheduler
        from memory.summaries.schemas import summary_config_from_memory_config
        from memory.summaries.verification.pipeline import LLMSummaryVerifierModel

        summary_cfg = summary_config_from_memory_config(config)
        register_summary_generator(
            self.service.registry,
            service=self.service,
            config=summary_cfg,
            generator_model=LLMSummaryGeneratorModel(
                LLMClient(settings, profile=config.summaries_model_profile),
                model_profile=config.summaries_model_profile,
                max_tokens=config.summaries_max_tokens,
            ),
            verifier_model=LLMSummaryVerifierModel(
                LLMClient(settings, profile=config.summaries_verify_model_profile),
                model_profile=config.summaries_verify_model_profile,
                max_tokens=config.summaries_max_tokens,
            )
            if summary_cfg.verify_enabled
            else None,
        )

        await self.runtime.start()
        set_text_ingest_sink(self.runtime.sink)
        await self.service.start_worker()

        self.verification_scheduler = VerificationScheduler(
            service=self.service,
            support_profile=settings.memory_verification_support_model_profile,
            adversarial_profile=settings.memory_verification_adversarial_model_profile,
            policy_version=settings.memory_verification_policy_version,
            interval_seconds=1.0,
            batch_size=50,
        )
        self.resolution_scheduler = ResolutionScheduler(
            service=self.service,
            required_verification_policy=settings.memory_required_verification_policy_version,
            interval_seconds=1.0,
            batch_size=50,
            support_profile=settings.memory_resolution_link_support_model_profile,
            adversarial_profile=settings.memory_resolution_link_adversarial_model_profile,
        )
        self.graph_scheduler = GraphOutboxScheduler(
            service=self.service,
            interval_seconds=0.5,
            batch_size=100,
        )
        await self.verification_scheduler.start()
        await self.resolution_scheduler.start()
        await self.graph_scheduler.start()
        self.summary_scheduler = SummaryDirtyScheduler(service=self.service)
        await self.summary_scheduler.start()

        # Align projection with current belief heads (incl. PR7 winners).
        from memory.graph.rebuild import rebuild_user_graph
        from memory.summaries.rebuild import mark_user_full_rebuild

        rebuild_user_graph(self.service.db, user_id=DEMO_USER_ID, store=self.service.graph)
        self.graph_scheduler.scan_once()
        mark_user_full_rebuild(
            self.service.db,
            user_id=DEMO_USER_ID,
            invalidator=self.service.summary_invalidator,
            communities=self.service.communities,
            config=summary_cfg,
        )
        self.summary_scheduler.scan_once()

        from memory.attachment.critics import LLMAttachmentCommitteeModel
        from memory.attachment.processor import register_attachment_analyzer
        from memory.attachment.react import LLMAttachmentReactModel
        from memory.attachment.scheduler import AttachmentDirtyScheduler
        from memory.attachment.schemas import attachment_config_from_memory_config

        attach_cfg = attachment_config_from_memory_config(config)
        attachment_max_tokens = max(4096, settings.memory_attachment_max_tokens)
        self.attachment_models = {
            "hypothesis": LLMAttachmentCommitteeModel(
                LLMClient(settings, profile=settings.memory_attachment_model_profile),
                model_profile=settings.memory_attachment_model_profile,
                max_tokens=attachment_max_tokens,
            ),
            "support": LLMAttachmentCommitteeModel(
                LLMClient(settings, profile=settings.memory_attachment_support_model_profile),
                model_profile=settings.memory_attachment_support_model_profile,
                max_tokens=attachment_max_tokens,
            ),
            "adversarial": LLMAttachmentCommitteeModel(
                LLMClient(settings, profile=settings.memory_attachment_adversarial_model_profile),
                model_profile=settings.memory_attachment_adversarial_model_profile,
                max_tokens=attachment_max_tokens,
            ),
            "cluster": LLMAttachmentCommitteeModel(
                LLMClient(settings, profile=settings.memory_attachment_cluster_model_profile),
                model_profile=settings.memory_attachment_cluster_model_profile,
                max_tokens=attachment_max_tokens,
            ),
            "react": (
                LLMAttachmentReactModel(
                    LLMClient(settings, profile=attach_cfg.react_model_profile),
                    model_profile=attach_cfg.react_model_profile,
                    max_tokens=attach_cfg.react_max_tokens,
                )
                if attach_cfg.react_enabled
                else None
            ),
        }
        register_attachment_analyzer(
            self.service.registry,
            service=self.service,
            hypothesis_model=self.attachment_models["hypothesis"],
            support_model=self.attachment_models["support"],
            adversarial_model=self.attachment_models["adversarial"],
            alt_model=self.attachment_models["hypothesis"],
            cluster_model=self.attachment_models["cluster"],
            research_model=self.attachment_models["react"],
        )
        self.attachment_scheduler = AttachmentDirtyScheduler(service=self.service)
        await self.attachment_scheduler.start()
        self.attachment_scheduler.scan_once()

        session = self.chat_store.get_or_create_active_session(
            DEMO_USER_ID,
            metadata={"graph_lab": True},
        )
        self.session_id = session.session_id
        logger.info(
            "graph lab ready db=%s policy=temporal_belief_v1+er+shadow+summaries+attachment",
            self.memory_path,
        )

    async def stop(self) -> None:
        from bot.memory_chat_adapter import set_text_ingest_sink

        if self.attachment_scheduler is not None:
            await self.attachment_scheduler.stop()
            self.attachment_scheduler = None
        self.attachment_models = {}
        if self.summary_scheduler is not None:
            await self.summary_scheduler.stop()
            self.summary_scheduler = None
        if self.graph_scheduler is not None:
            await self.graph_scheduler.stop()
            self.graph_scheduler = None
        if self.resolution_scheduler is not None:
            await self.resolution_scheduler.stop()
            self.resolution_scheduler = None
        if self.verification_scheduler is not None:
            await self.verification_scheduler.stop()
            self.verification_scheduler = None
        set_text_ingest_sink(None)
        if self.runtime is not None:
            await self.runtime.stop(grace_seconds=1.0)
            self.runtime = None
        if self.service is not None:
            await self.service.stop_worker(grace_seconds=1.0)
            self.service = None
        self.chat_store = None
        self.session_id = None

    @staticmethod
    def _checkpoint_and_unlink(path: Path, *, attempts: int = 12) -> None:
        """Release WAL handles then delete sqlite (+wal/shm). Windows-safe."""
        import gc
        import sqlite3
        import time

        sides = [path, Path(str(path) + "-wal"), Path(str(path) + "-shm")]
        if path.exists():
            try:
                conn = sqlite3.connect(str(path), timeout=30.0)
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.commit()
                finally:
                    conn.close()
            except Exception:  # noqa: BLE001
                logger.warning("sqlite checkpoint failed for %s", path, exc_info=True)
        gc.collect()
        time.sleep(0.05)
        for _ in range(attempts):
            pending = [p for p in sides if p.exists()]
            if not pending:
                return
            for item in pending:
                try:
                    item.unlink()
                except OSError:
                    pass
            gc.collect()
            time.sleep(0.15)
        leftover = [str(p) for p in sides if p.exists()]
        if leftover:
            raise OSError(f"could not delete locked sqlite files: {leftover}")

    def graph_payload(self) -> dict[str, Any]:
        assert self.service is not None
        from memory.graph.schemas import SUBJECT_ROLES, edge_type_for
        from memory.ids import make_graph_node_id

        nodes = self.service.graph.list_active_nodes(user_id=DEMO_USER_ID)
        edges = self.service.graph.list_active_edges(user_id=DEMO_USER_ID)
        revision = self.service.graph.current_revision(DEMO_USER_ID)

        node_by_source: dict[str, dict[str, Any]] = {}
        out_nodes: list[dict[str, Any]] = []
        for row in nodes:
            item = {
                "id": str(row["node_id"]),
                "label": row["label"] or row["source_record_id"],
                "node_type": row["node_type"],
                "properties": json.loads(row["properties_json"] or "{}"),
                "deferred": False,
                "historical": False,
            }
            out_nodes.append(item)
            node_by_source[str(row["source_record_id"])] = item

        out_edges: list[dict[str, Any]] = []
        for row in edges:
            props = json.loads(row.get("properties_json") or "{}")
            if not isinstance(props, dict):
                props = {}
            edge_type = str(row["edge_type"] or "")
            is_attach = edge_type.startswith("attach:")
            out_edges.append(
                {
                    "id": str(row["edge_id"]),
                    "from": str(row["from_node_id"]),
                    "to": str(row["to_node_id"]),
                    "edge_type": edge_type,
                    "belief_id": row["belief_id"],
                    "deferred": False,
                    "historical": False,
                    "attach": is_attach,
                    "utility_class": props.get("utility_class"),
                    "attachment_event_id": props.get("event_id"),
                    "attachment_tier": props.get("tier"),
                    "attachment_version": props.get("attachment_version"),
                    "polarity": props.get("polarity", "positive"),
                    "reasons": [],
                }
            )

        def ensure_entity_node(entity_id: str) -> str | None:
            if entity_id in node_by_source:
                return str(node_by_source[entity_id]["id"])
            with self.service.db.connection() as conn:
                ent = conn.execute(
                    """
                    SELECT entity_id, entity_type, identity_key, canonical_label, status
                    FROM memory_entities
                    WHERE entity_id = ? AND user_id = ?
                    """,
                    (entity_id, DEMO_USER_ID),
                ).fetchone()
            if ent is None:
                return None
            entity_type = str(ent["entity_type"])
            node_type = "concept" if entity_type == "concept" else "entity"
            node_id = make_graph_node_id(
                user_id=DEMO_USER_ID,
                node_type=node_type,
                source_record_id=str(ent["entity_id"]),
            )
            item = {
                "id": node_id,
                "label": str(ent["canonical_label"] or ent["identity_key"]),
                "node_type": node_type,
                "properties": {
                    "entity_type": entity_type,
                    "identity_key": str(ent["identity_key"]),
                    "entity_status": str(ent["status"]),
                },
                "deferred": True,
            }
            # Prefer existing durable node id if same.
            existing = next((n for n in out_nodes if n["id"] == node_id), None)
            if existing is None:
                out_nodes.append(item)
                node_by_source[entity_id] = item
            else:
                node_by_source[entity_id] = existing
            return node_id

        with self.service.db.connection() as conn:
            overlay_rows = conn.execute(
                """
                SELECT h.belief_id, b.schema_name,
                       r.belief_status, r.utility_class, r.utility_reason_codes_json,
                       r.resolved_arguments_json, r.polarity,
                       (
                         SELECT a.candidate_kind
                         FROM memory_belief_support s
                         JOIN memory_assertions a ON a.assertion_id = s.assertion_id
                         WHERE s.belief_revision_id = r.belief_revision_id
                           AND s.relation = 'supports'
                         ORDER BY a.created_at DESC LIMIT 1
                       ) AS candidate_kind,
                       (
                         SELECT a.schema_name
                         FROM memory_belief_support s
                         JOIN memory_assertions a ON a.assertion_id = s.assertion_id
                         WHERE s.belief_revision_id = r.belief_revision_id
                           AND s.relation = 'supports'
                         ORDER BY a.created_at DESC LIMIT 1
                       ) AS assertion_schema
                FROM memory_belief_heads h
                JOIN memory_beliefs b ON b.belief_id = h.belief_id
                JOIN memory_belief_revisions r
                  ON r.belief_revision_id = h.belief_revision_id
                WHERE h.user_id = ?
                  AND (
                    (r.belief_status = 'active' AND r.utility_class = 'deferred')
                    OR r.belief_status = 'historical'
                  )
                ORDER BY h.belief_id
                """,
                (DEMO_USER_ID,),
            ).fetchall()

        solid_belief_ids = {
            e["belief_id"] for e in out_edges if not e.get("deferred") and not e.get("historical")
        }

        for row in overlay_rows:
            kind = str(row["candidate_kind"] or "claim")
            schema = str(row["assertion_schema"] or row["schema_name"] or "unknown")
            historical = str(row["belief_status"]) == "historical"
            deferred = (
                not historical
                and str(row["utility_class"]) == "deferred"
                and str(row["belief_status"]) == "active"
            )
            # Meta correction lineage is not a domain edge; skip overlay noise.
            if kind == "correction" or schema.startswith("corrects"):
                continue
            if str(row["belief_id"]) in solid_belief_ids:
                continue
            args = json.loads(str(row["resolved_arguments_json"] or "[]"))
            if not isinstance(args, list):
                continue
            usable = [a for a in args if isinstance(a, dict) and a.get("entity_id")]
            if len(usable) < 2:
                continue
            subject_idx = 0
            for i, item in enumerate(usable):
                if str(item.get("role") or "").lower() in SUBJECT_ROLES:
                    subject_idx = i
                    break
            to_idx = next(
                (i for i in range(len(usable)) if i != subject_idx),
                None,
            )
            if to_idx is None:
                continue
            from_id = ensure_entity_node(str(usable[subject_idx]["entity_id"]))
            to_id = ensure_entity_node(str(usable[to_idx]["entity_id"]))
            if not from_id or not to_id:
                continue
            reasons = json.loads(str(row["utility_reason_codes_json"] or "[]"))
            edge_type = edge_type_for(kind=kind, schema_name=schema)
            if any(
                (not e.get("deferred") and not e.get("historical"))
                and e.get("from") == from_id
                and e.get("to") == to_id
                and e.get("edge_type") == edge_type
                for e in out_edges
            ):
                continue
            # Mark overlay nodes.
            for nid in (from_id, to_id):
                for n in out_nodes:
                    if n["id"] == nid and (deferred or historical):
                        if historical:
                            n["historical"] = True
                        if deferred and not n.get("historical"):
                            n["deferred"] = True
            out_edges.append(
                {
                    "id": f"{'historical' if historical else 'deferred'}:{row['belief_id']}",
                    "from": from_id,
                    "to": to_id,
                    "edge_type": edge_type,
                    "belief_id": str(row["belief_id"]),
                    "deferred": deferred,
                    "historical": historical,
                    "polarity": str(row["polarity"] or "unknown"),
                    "reasons": reasons if isinstance(reasons, list) else [],
                }
            )

        # Overlay active attachment events that aren't graph edges yet.
        solid_attach_keys = {
            (e["from"], e["to"], e["edge_type"])
            for e in out_edges
            if e.get("attach") or str(e.get("edge_type") or "").startswith("attach:")
        }
        attach_rows = self.service.attachment_events.list_for_user(
            user_id=DEMO_USER_ID,
            limit=100,
            status="active",
        )
        for ev in attach_rows:
            from_id = ensure_entity_node(ev.source_entity_id)
            to_id = ensure_entity_node(ev.target_entity_id)
            if not from_id or not to_id:
                continue
            edge_type = f"attach:{ev.op}"
            key = (from_id, to_id, edge_type)
            if key in solid_attach_keys:
                continue
            solid_attach_keys.add(key)
            deferred = ev.utility_class == "deferred"
            out_edges.append(
                {
                    "id": f"attach:{ev.event_id}",
                    "from": from_id,
                    "to": to_id,
                    "edge_type": edge_type,
                    "belief_id": ev.source_belief_id or ev.event_id,
                    "deferred": deferred,
                    "historical": False,
                    "attach": True,
                    "utility_class": ev.utility_class,
                    "reasons": [],
                }
            )

        from memory.resolution.schemas import RECONCILIATION_POLICY_VERSION

        return {
            "revision": revision,
            "nodes": out_nodes,
            "edges": out_edges,
            "policy": RECONCILIATION_POLICY_VERSION,
        }

    def status_payload(self) -> dict[str, Any]:
        assert self.service is not None
        base = self.service.status()
        cfg = self.service.config
        with self.service.db.connection() as conn:
            merge_events = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM memory_entity_resolution_events
                    WHERE user_id = ? AND status = 'active'
                    """,
                    (DEMO_USER_ID,),
                ).fetchone()["c"]
            )
            shadow_runs = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM memory_shadow_retrieval_runs
                    WHERE user_id = ?
                    """,
                    (DEMO_USER_ID,),
                ).fetchone()["c"]
            )
        dirty = self.service.summary_dirty.backlog_count(user_id=DEMO_USER_ID)
        communities = self.service.communities.count_active(user_id=DEMO_USER_ID)
        summaries_active = self.service.summaries.count_by_status(
            user_id=DEMO_USER_ID
        ).get("active", 0)
        with self.service.db.connection() as conn:
            attach_reverted = int(conn.execute(
                "SELECT COUNT(*) AS c FROM memory_attachment_events WHERE user_id=? AND status='reverted'",
                (DEMO_USER_ID,),
            ).fetchone()["c"])
            attach_constraints = int(conn.execute(
                "SELECT COUNT(*) AS c FROM memory_attachment_constraints WHERE user_id=? AND status='active'",
                (DEMO_USER_ID,),
            ).fetchone()["c"])
            attach_dependencies = int(conn.execute(
                "SELECT COUNT(*) AS c FROM memory_attachment_dependencies WHERE user_id=? AND status='active'",
                (DEMO_USER_ID,),
            ).fetchone()["c"])
        return {
            "flags": {
                "shadow_retrieval_enabled": cfg.shadow_retrieval_enabled,
                "resolution_candidate_generation_enabled": (
                    cfg.resolution_candidate_generation_enabled
                ),
                "resolution_merge_events_enabled": cfg.resolution_merge_events_enabled,
                "summaries_enabled": cfg.summaries_enabled,
                "summaries_generation_enabled": cfg.summaries_generation_enabled,
                "summaries_communities_enabled": cfg.summaries_communities_enabled,
                "summaries_shadow_pack_enabled": cfg.summaries_shadow_pack_enabled,
                "attachment_enabled": cfg.attachment_enabled,
                "attachment_generation_enabled": cfg.attachment_generation_enabled,
                "attachment_react_enabled": cfg.attachment_react_enabled,
                "attachment_react_mode": cfg.attachment_react_mode,
            },
            "status": _memory_status_dict(base),
            "merge_events": merge_events,
            "shadow_runs": shadow_runs,
            "dirty": dirty,
            "attach_dirty": self.service.attachment_dirty.backlog_count(user_id=DEMO_USER_ID),
            "attach_events": self.service.attachment_events.count_active(user_id=DEMO_USER_ID),
            "attach_reverted": attach_reverted,
            "attach_constraints": attach_constraints,
            "attach_dependencies": attach_dependencies,
            "communities": communities,
            "summaries_active": summaries_active,
        }

    def summaries_payload(self) -> dict[str, Any]:
        assert self.service is not None
        records = self.service.summaries.list_active_for_user(
            user_id=DEMO_USER_ID,
            limit=50,
        )
        return {
            "summaries": [
                {
                    "summary_id": row.summary_id,
                    "summary_type": row.summary_type,
                    "target_id": row.target_id,
                    "content_preview": _text_preview(row.content, limit=200),
                    "belief_ids_count": len(row.belief_ids),
                    "status": row.status,
                }
                for row in records
            ]
        }

    def attach_events_payload(self) -> dict[str, Any]:
        assert self.service is not None
        with self.service.db.connection() as conn:
            records = conn.execute(
                """
                SELECT e.*,
                       src.canonical_label AS source_label,
                       tgt.canonical_label AS target_label,
                       (SELECT COUNT(*) FROM memory_attachment_dependencies d
                        WHERE d.event_id=e.event_id) AS dependency_count
                FROM memory_attachment_events e
                LEFT JOIN memory_entities src ON src.entity_id=e.source_entity_id
                LEFT JOIN memory_entities tgt ON tgt.entity_id=e.target_entity_id
                WHERE e.user_id=? ORDER BY e.created_at DESC LIMIT 100
                """,
                (DEMO_USER_ID,),
            ).fetchall()
            constraints = conn.execute(
                """
                SELECT c.*,e.canonical_label AS target_label
                FROM memory_attachment_constraints c
                LEFT JOIN memory_entities e ON e.entity_id=c.target_entity_id
                WHERE c.user_id=? ORDER BY c.updated_at DESC LIMIT 50
                """,
                (DEMO_USER_ID,),
            ).fetchall()
        return {
            "events": [
                {
                    "event_id": str(row["event_id"]),
                    "op": str(row["op"]),
                    "source_belief_id": row["source_belief_id"],
                    "source_entity_id": str(row["source_entity_id"]),
                    "source_label": row["source_label"],
                    "target_entity_id": str(row["target_entity_id"]),
                    "target_label": row["target_label"],
                    "status": str(row["status"]),
                    "utility_class": str(row["utility_class"]),
                    "tier": str(row["tier"]),
                    "supersedes_event_id": row["supersedes_event_id"],
                    "graph_revision": row["graph_revision"],
                    "dependency_count": int(row["dependency_count"]),
                    "created_at": str(row["created_at"]),
                }
                for row in records
            ],
            "constraints": [
                {
                    "constraint_id": str(row["constraint_id"]),
                    "constraint_type": str(row["constraint_type"]),
                    "target_entity_id": str(row["target_entity_id"]),
                    "target_label": row["target_label"],
                    "scope": str(row["scope"]),
                    "source_belief_id": str(row["source_belief_id"]),
                    "status": str(row["status"]),
                }
                for row in constraints
            ],
        }

    async def attach_dry_run(self, belief_id: str) -> dict[str, Any]:
        assert self.service is not None
        from dataclasses import asdict
        from memory.attachment.pipeline import analyze_attachment
        from memory.attachment.schemas import attachment_config_from_memory_config

        cfg = attachment_config_from_memory_config(self.service.config)
        research: dict[str, Any] = {}
        with self.service.db.connection() as conn:
            result = await analyze_attachment(
                conn,
                user_id=DEMO_USER_ID,
                belief_id=belief_id,
                config=cfg,
                hypothesis_model=self.attachment_models.get("hypothesis"),
                support_model=self.attachment_models.get("support"),
                adversarial_model=self.attachment_models.get("adversarial"),
                alt_model=self.attachment_models.get("hypothesis"),
                cluster_model=self.attachment_models.get("cluster"),
                research_model=self.attachment_models.get("react"),
                research_sink=research,
                commit=False,
            )
        return {
            "belief_id": belief_id,
            "accepted": result.accepted,
            "abstain_reason": result.abstain_reason,
            "hypothesis": asdict(result.hypothesis) if result.hypothesis else None,
            "accepted_hypotheses": [
                {
                    **asdict(item),
                    "target_label": next(
                        (candidate.label for candidate in result.shortlist if candidate.target_id == item.target_id),
                        item.target_id,
                    ),
                }
                for item in result.accepted_hypotheses
            ],
            "utility_class": result.utility_class,
            "tier": result.tier,
            "shortlist": [
                {
                    "target_id": c.target_id,
                    "label": c.label,
                    "score": c.score,
                    "channel": c.channel,
                    "op_hint": c.op_hint,
                    "entity_type": c.entity_type,
                    "metadata": dict(c.metadata or {}),
                }
                for c in result.shortlist
            ],
            "layer_trace": [asdict(layer) for layer in result.layer_trace],
            "llm_calls": result.llm_calls,
            "research": research or None,
        }

    def latest_attachment_research(self, belief_id: str | None) -> dict[str, Any] | None:
        if not belief_id:
            return None
        assert self.service is not None
        with self.service.db.connection() as conn:
            row = conn.execute(
                """
                SELECT output_json FROM memory_jobs
                WHERE user_id=? AND stage='attach_analyze' AND target_id=?
                  AND status='done' AND output_json IS NOT NULL
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (DEMO_USER_ID, belief_id),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["output_json"]))
        except (TypeError, json.JSONDecodeError):
            return None
        research = payload.get("research")
        return research if isinstance(research, dict) else None

    async def run_shadow(self, query: str) -> dict[str, Any]:
        assert self.service is not None
        from memory.retrieval.shadow import run_shadow_preflight

        try:
            result = await run_shadow_preflight(
                memory_service=self.service,
                user_id=DEMO_USER_ID,
                query=query,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("shadow preflight failed")
            return _shadow_api_payload(None, error=str(exc))
        return _shadow_api_payload(result)

    async def wait_settled(
        self,
        *,
        timeout: float = 180.0,
        wait_summaries: bool = False,
    ) -> dict[str, Any]:
        """Wait until the belief→graph pipeline is idle.

        By default does NOT wait for PR12 summary_generate jobs / dirty queue —
        those are slow LLM work and would block the UI from painting the graph.
        """
        assert self.service is not None
        deadline = asyncio.get_running_loop().time() + timeout
        last: dict[str, Any] = {}
        while True:
            if self.verification_scheduler is not None:
                self.verification_scheduler.scan_once()
            if self.resolution_scheduler is not None:
                self.resolution_scheduler.scan_once()
            if self.graph_scheduler is not None:
                self.graph_scheduler.scan_once()
            if self.summary_scheduler is not None:
                self.summary_scheduler.scan_once()
            if self.attachment_scheduler is not None:
                self.attachment_scheduler.scan_once()
            self.service.wake_worker()
            with self.service.db.connection() as conn:
                jobs = {
                    str(row["status"]): int(row["count"])
                    for row in conn.execute(
                        "SELECT status, COUNT(*) AS count FROM memory_jobs GROUP BY status"
                    ).fetchall()
                }
                graph_in_flight = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS c FROM memory_jobs
                        WHERE status IN ('pending', 'running')
                          AND stage NOT IN ('summary_generate', 'attach_analyze')
                        """
                    ).fetchone()["c"]
                )
                summary_in_flight = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS c FROM memory_jobs
                        WHERE status IN ('pending', 'running')
                          AND stage = 'summary_generate'
                        """
                    ).fetchone()["c"]
                )
                attach_in_flight = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS c FROM memory_jobs
                        WHERE status IN ('pending', 'running')
                          AND stage = 'attach_analyze'
                        """
                    ).fetchone()["c"]
                )
                pending_outbox = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS c FROM graph_outbox
                        WHERE status IN ('pending', 'processing')
                        """
                    ).fetchone()["c"]
                )
                ready = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS c FROM memory_claim_candidates
                        WHERE user_id = ? AND status = 'ready_for_resolution'
                        """,
                        (DEMO_USER_ID,),
                    ).fetchone()["c"]
                )
                unresolved_ready = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS c
                        FROM memory_claim_candidates c
                        JOIN memory_candidate_scores s
                          ON s.candidate_id = c.candidate_id
                         AND s.status = 'active'
                         AND s.route_status = 'ready_for_resolution'
                        WHERE c.user_id = ?
                          AND c.status = 'ready_for_resolution'
                          AND NOT EXISTS (
                              SELECT 1 FROM memory_assertions a
                              WHERE a.candidate_id = c.candidate_id
                                AND a.status IN ('active', 'historical')
                          )
                        """,
                        (DEMO_USER_ID,),
                    ).fetchone()["c"]
                )
                dirty_backlog = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS c
                        FROM graph_summary_dirty
                        WHERE user_id = ?
                        """,
                        (DEMO_USER_ID,),
                    ).fetchone()["c"]
                )
            queue = self.runtime.status().queue_size if self.runtime else 0
            last = {
                "jobs": jobs,
                "in_flight": graph_in_flight + summary_in_flight + attach_in_flight,
                "graph_in_flight": graph_in_flight,
                "summary_in_flight": summary_in_flight,
                "attach_in_flight": attach_in_flight,
                "queue": queue,
                "pending_outbox": pending_outbox,
                "ready": ready,
                "unresolved_ready": unresolved_ready,
                "dirty_backlog": dirty_backlog,
            }
            graph_idle = (
                graph_in_flight == 0
                and queue == 0
                and pending_outbox == 0
                and unresolved_ready == 0
            )
            summaries_idle = dirty_backlog == 0 and summary_in_flight == 0
            if graph_idle and (not wait_summaries or summaries_idle):
                return last
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"pipeline did not settle: {last}")
            await asyncio.sleep(0.2)

    async def add_message(self, text: str) -> dict[str, Any]:
        assert self.chat_store is not None and self.session_id is not None
        async with self._lock:
            ids = self.chat_store.append_messages(
                self.session_id,
                DEMO_USER_ID,
                [{"role": "user", "content": text}],
                default_source_at=datetime.now(timezone.utc),
            )
            from bot.memory_chat_adapter import notify_chat_ingested

            notify_chat_ingested(user_id=DEMO_USER_ID, message_ids=ids)
            # Return as soon as graph projection is ready; summaries keep running.
            settle = await self.wait_settled(wait_summaries=False)
            graph = self.graph_payload()
            status = self.status_payload()
            summaries = self.summaries_payload()
            attach = self.attach_events_payload()
            shadow = await self.run_shadow(text)
            with self.service.db.connection() as conn:
                cand_n = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS c FROM memory_claim_candidates
                        WHERE user_id = ? AND status NOT IN ('invalidated', 'superseded')
                        """,
                        (DEMO_USER_ID,),
                    ).fetchone()["c"]
                )
                belief_n = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS c FROM memory_belief_heads WHERE user_id = ?
                        """,
                        (DEMO_USER_ID,),
                    ).fetchone()["c"]
                )
                latest_belief = conn.execute(
                    """
                    SELECT belief_id FROM memory_belief_heads
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (DEMO_USER_ID,),
                ).fetchone()
            latest_belief_id = str(latest_belief["belief_id"]) if latest_belief else None
            latest_research = self.latest_attachment_research(latest_belief_id)
            return {
                "message_ids": list(ids),
                "settle": settle,
                "latest_belief_id": latest_belief_id,
                "summary": (
                    f"candidates={cand_n} beliefs={belief_n} "
                    f"nodes={len(graph['nodes'])} edges={len(graph['edges'])} | "
                    f"summaries={status['summaries_active']} "
                    f"communities={status['communities']} dirty={status['dirty']} "
                    f"attach={status['attach_events']} attach_dirty={status['attach_dirty']} "
                    f"merges={status['merge_events']} shadow_runs={status['shadow_runs']}"
                ),
                "status": status,
                "summaries": summaries["summaries"],
                "attach_events": attach["events"],
                "shadow": shadow,
                "attachment_research": latest_research,
                "graph": graph,
            }

    async def reset(self) -> dict[str, Any]:
        """Hard reset lab DBs so the demo graph starts empty again."""
        async with self._lock:
            await self.stop()
            # Give worker threads a beat to drop sqlite handles (Windows).
            await asyncio.sleep(0.25)
            for path in (self.chat_path, self.tool_path, self.memory_path):
                self._checkpoint_and_unlink(path)
            await self.start()
            return {
                "graph": self.graph_payload(),
                "status": self.status_payload(),
                "summaries": self.summaries_payload()["summaries"],
            }


async def main_async(host: str, port: int) -> None:
    lab = GraphLab(ROOT)
    await lab.start()

    async def index(_request: web.Request) -> web.Response:
        return web.Response(text=INDEX_HTML, content_type="text/html")

    async def api_graph(_request: web.Request) -> web.Response:
        return web.json_response(lab.graph_payload())

    async def api_status(_request: web.Request) -> web.Response:
        return web.json_response(lab.status_payload())

    async def api_summaries(_request: web.Request) -> web.Response:
        return web.json_response(lab.summaries_payload())

    async def api_shadow(request: web.Request) -> web.Response:
        query = str(request.query.get("q") or "").strip()
        if not query:
            return web.json_response({"error": "empty query"}, status=400)
        try:
            result = await lab.run_shadow(query)
        except Exception as exc:  # noqa: BLE001
            logger.exception("shadow failed")
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response(result)

    async def api_message(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        text = str(body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "empty text"}, status=400)
        try:
            result = await lab.add_message(text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("add_message failed")
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response(result)

    async def api_reset(_request: web.Request) -> web.Response:
        try:
            result = await lab.reset()
        except Exception as exc:  # noqa: BLE001
            logger.exception("reset failed")
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response(result)

    async def api_attach(request: web.Request) -> web.Response:
        belief_id = str(request.query.get("belief_id") or "").strip()
        if not belief_id:
            return web.json_response({"error": "belief_id required"}, status=400)
        try:
            result = await lab.attach_dry_run(belief_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("attach dry-run failed")
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response(result)

    async def api_attach_events(_request: web.Request) -> web.Response:
        return web.json_response(lab.attach_events_payload())

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/graph", api_graph)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/summaries", api_summaries)
    app.router.add_get("/api/attach", api_attach)
    app.router.add_get("/api/attach/events", api_attach_events)
    app.router.add_get("/api/shadow", api_shadow)
    app.router.add_post("/api/message", api_message)
    app.router.add_post("/api/reset", api_reset)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"Graph lab: http://{host}:{port}")
    try:
        await asyncio.Event().wait()
    finally:
        await lab.stop()
        await runner.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args.host, args.port))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
