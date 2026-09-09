"""Economy Town live dashboard: reads economy.db and visualizes simulation state.

Run:
    streamlit run dashboard.py
"""

import datetime as dt
import json
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from economy.config import DB_PATH
from economy.engine import phase_and_day

st.set_page_config(page_title="Economy Town", page_icon="🏚️", layout="wide")

ROLE_ICONS = {"Financier": "🏦", "Worker": "🔨", "Farmer": "🌾"}
RESOURCE_ICONS = {"food": "🍞", "water": "💧", "gold": "🪙", "debt_note": "📜"}
STATUS_LABELS = {"ok": "Stable", "hungry": "Hungry", "thirsty": "Thirsty", "critical": "Critical", "dead": "Deceased"}
STATUS_STYLE = {
    "ok": {"accent": "#2ecc71", "tint": "rgba(46, 199, 113, 0.12)"},
    "hungry": {"accent": "#f0ad0e", "tint": "rgba(240, 173, 14, 0.12)"},
    "thirsty": {"accent": "#f0ad0e", "tint": "rgba(240, 173, 14, 0.12)"},
    "critical": {"accent": "#e74c3c", "tint": "rgba(231, 76, 60, 0.14)"},
    "dead": {"accent": "#7f8c8d", "tint": "rgba(127, 140, 141, 0.18)"},
}

CARD_CSS = """
<style>
.agent-card {
    border-radius: 14px;
    padding: 18px 12px 14px;
    text-align: center;
    border: 1.5px solid var(--accent);
    background: var(--tint);
    height: 100%;
}
.agent-card.dead { opacity: 0.65; filter: grayscale(45%); }
.agent-avatar { font-size: 34px; line-height: 1; }
.agent-name { font-weight: 700; font-size: 17px; margin-top: 6px; }
.agent-role { font-size: 12px; opacity: 0.65; margin-bottom: 8px; }
.agent-status {
    display: inline-block;
    padding: 2px 12px;
    border-radius: 999px;
    background: var(--accent);
    color: white;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    margin-bottom: 10px;
}
.agent-resources {
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 6px 10px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
}
.event-card {
    border-radius: 10px;
    padding: 10px 14px;
    margin-bottom: 8px;
    border-left: 4px solid var(--accent);
    background: var(--tint);
    font-size: 14px;
}
.dm-bubble-row { display: flex; margin-bottom: 10px; }
.dm-bubble-row.left { justify-content: flex-start; }
.dm-bubble-row.right { justify-content: flex-end; }
.dm-bubble {
    max-width: 70%;
    padding: 10px 14px;
    border-radius: 16px;
    font-size: 14px;
    line-height: 1.45;
}
.dm-bubble.left { background: rgba(127, 140, 141, 0.16); border-bottom-left-radius: 4px; }
.dm-bubble.right { background: rgba(91, 141, 239, 0.22); border-bottom-right-radius: 4px; }
.dm-meta { font-size: 11px; opacity: 0.6; margin-bottom: 3px; }
</style>
"""


def agent_card_html(name: str, role: str, status: str, resources: dict, is_leader: bool = False) -> str:
    style = STATUS_STYLE.get(status, STATUS_STYLE["ok"])
    avatar = ROLE_ICONS.get(role, "🧑")
    label = STATUS_LABELS.get(status, status)
    dead_class = "dead" if status == "dead" else ""
    crown = '<div style="font-size:20px;line-height:1;">👑</div>' if is_leader else ""
    res_html = "".join(
        f"<span>{RESOURCE_ICONS.get(res, '•')} {round(val, 1) if isinstance(val, float) else val}</span>"
        for res, val in resources.items()
    )
    return (
        f'<div class="agent-card {dead_class}" style="--accent:{style["accent"]};--tint:{style["tint"]}">'
        f"{crown}"
        f'<div class="agent-avatar">{avatar}</div>'
        f'<div class="agent-name">{name}</div>'
        f'<div class="agent-role">{role}</div>'
        f'<div class="agent-status">{label}</div>'
        f'<div class="agent-resources">{res_html}</div>'
        f"</div>"
    )


def event_card_html(text: str, accent: str, tint: str) -> str:
    return f'<div class="event-card" style="--accent:{accent};--tint:{tint}">{text}</div>'


def gini_coefficient(values: list[float]) -> float:
    """0 = everyone has equal wealth, closer to 1 = extreme inequality.

    Values can be negative (net debtors) — shifted to non-negative first, since the
    classic Gini formula assumes non-negative wealth.
    """
    arr = np.array(values, dtype=float)
    n = len(arr)
    if n == 0:
        return 0.0
    if arr.min() < 0:
        arr = arr - arr.min()
    total = arr.sum()
    if total == 0:
        return 0.0
    sorted_arr = np.sort(arr)
    ranks = np.arange(1, n + 1)
    return float((2 * np.sum(ranks * sorted_arr) / (n * total)) - (n + 1) / n)


def wealth_by_round(states: pd.DataFrame, price_pivot: pd.DataFrame) -> pd.DataFrame:
    """Net worth per agent per round, valuing food/water/debt_note at that round's
    market price so it's all comparable in one unit (gold-equivalent)."""
    records = []
    for _, row in states.iterrows():
        res = json.loads(row["resources_json"])
        rnd = row["round"]
        p = price_pivot.loc[rnd] if rnd in price_pivot.index else pd.Series(dtype=float)
        wealth = (
            res.get("gold", 0)
            + res.get("food", 0) * p.get("food", 0)
            + res.get("water", 0) * p.get("water", 0)
            + res.get("debt_note", 0) * p.get("debt_note", 0)
        )
        records.append({"round": rnd, "agent": row["agent"], "wealth": wealth})
    return pd.DataFrame(records)


def live_status_line(tx: pd.DataFrame) -> str:
    """A little 'the town is alive right now' readout: when the last phase actually
    ran (real timestamp) and when the next one is due, based on the GitHub Actions
    schedule (:07 and :37 past every hour)."""
    try:
        latest = dt.datetime.fromisoformat(tx["timestamp"].max())
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return ""

    now = dt.datetime.now(dt.timezone.utc)
    minutes_since = max(int((now - latest).total_seconds() // 60), 0)

    candidates = []
    for hour_offset in (0, 1):
        base = (now + dt.timedelta(hours=hour_offset)).replace(second=0, microsecond=0)
        for minute in (7, 37):
            candidate = base.replace(minute=minute)
            if candidate > now:
                candidates.append(candidate)
    next_tick = min(candidates)
    minutes_until = max(int((next_tick - now).total_seconds() // 60) + 1, 0)

    return (
        f"🕐 Town last moved **{minutes_since} min ago** · next tick in **~{minutes_until} min** "
        "(automatic, every 30 min via GitHub Actions)"
    )


def compute_leader(tx: pd.DataFrame) -> tuple[str, int] | None:
    """The agent with the most vote_leader stances across the whole run so far."""
    votes = tx[tx["stance"] == "vote_leader"]
    if votes.empty:
        return None
    tally = votes["stance_target"].value_counts()
    return tally.index[0], int(tally.iloc[0])


def compute_alliances(tx: pd.DataFrame) -> set[frozenset]:
    """Mutual propose_alliance pairs — real alliances only form when both sides propose."""
    proposals = tx[tx["stance"] == "propose_alliance"]
    proposed_by: dict[str, set[str]] = {}
    for _, row in proposals.iterrows():
        proposed_by.setdefault(row["agent"], set()).add(row["stance_target"])
    alliances = set()
    for a, targets in proposed_by.items():
        for b in targets:
            if a in proposed_by.get(b, set()):
                alliances.add(frozenset((a, b)))
    return alliances


def compute_boycotts(tx: pd.DataFrame) -> set[frozenset]:
    boycotts = tx[tx["stance"] == "boycott"]
    return {frozenset((row["agent"], row["stance_target"])) for _, row in boycotts.iterrows()}


def build_relationship_graph(tx: pd.DataFrame, agent_role_map: dict, alliances: set, boycotts: set):
    """Who's-connected-to-whom map: nodes = agents, edges = DMs (blue, thickness = volume),
    alliances (solid green), boycotts (dashed red)."""
    dms = tx[tx["private_message"].notna() & (tx["private_message"] != "") & tx["dm_target"].notna()]
    edge_counts: dict[tuple[str, str], int] = {}
    for _, row in dms.iterrows():
        pair = tuple(sorted([row["agent"], row["dm_target"]]))
        edge_counts[pair] = edge_counts.get(pair, 0) + 1

    agents = sorted(agent_role_map.keys())
    n = len(agents)
    if n == 0:
        return None
    positions = {
        name: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n))
        for i, name in enumerate(agents)
    }

    fig = go.Figure()
    if edge_counts:
        max_count = max(edge_counts.values())
        for (a, b), count in edge_counts.items():
            if frozenset((a, b)) in alliances or frozenset((a, b)) in boycotts:
                continue  # drawn separately below, with priority styling
            x0, y0 = positions[a]
            x1, y1 = positions[b]
            fig.add_trace(go.Scatter(
                x=[x0, x1], y=[y0, y1], mode="lines",
                line=dict(width=1 + 6 * count / max_count, color="rgba(91, 141, 239, 0.55)"),
                hoverinfo="text", text=f"{a} ↔ {b}: {count} DM(s)", showlegend=False,
            ))

    for pair in alliances:
        a, b = tuple(pair)
        x0, y0 = positions[a]
        x1, y1 = positions[b]
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[y0, y1], mode="lines",
            line=dict(width=4, color="rgba(46, 199, 113, 0.85)"),
            hoverinfo="text", text=f"🤝 {a} ↔ {b}: allied", showlegend=False,
        ))

    for pair in boycotts:
        a, b = tuple(pair)
        x0, y0 = positions[a]
        x1, y1 = positions[b]
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[y0, y1], mode="lines",
            line=dict(width=3, color="rgba(231, 76, 60, 0.85)", dash="dash"),
            hoverinfo="text", text=f"🚫 {a} ↔ {b}: boycotted", showlegend=False,
        ))

    node_x = [positions[a][0] for a in agents]
    node_y = [positions[a][1] for a in agents]
    node_labels = [f"{ROLE_ICONS.get(agent_role_map[a], '🧑')} {a}" for a in agents]
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y, mode="markers+text", text=node_labels, textposition="top center",
        marker=dict(size=28, color="#5b8def", line=dict(width=2, color="white")),
        hoverinfo="text", showlegend=False,
    ))
    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False, range=[-1.4, 1.4]),
        yaxis=dict(visible=False, range=[-1.4, 1.4]),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


ZONE_CENTERS = {
    "Bank": (0.0, 1.3),
    "Workshops": (1.15, -0.85),
    "Farms": (-1.15, -0.85),
    "Town Square": (0.0, -0.05),
}
ZONE_LABELS = {"Bank": "🏦 Bank", "Workshops": "🔨 Workshops", "Farms": "🌾 Farms", "Town Square": "🏛️ Town Square"}
ROLE_HOME_ZONE = {"Financier": "Bank", "Worker": "Workshops", "Farmer": "Farms"}


def build_town_map(tx_day: pd.DataFrame, agent_role_map: dict, status_by_agent: dict, location_by_agent: dict, leader_name):
    """A top-down schematic map: agents sit wherever they declared they'd be this time
    of day (falling back to their role's home zone for older data with no location
    recorded), arrows show who went to whom — blue for economic actions, purple for DMs."""
    by_zone: dict[str, list[str]] = {}
    for name, role in agent_role_map.items():
        zone = location_by_agent.get(name) or ROLE_HOME_ZONE.get(role, "Town Square")
        by_zone.setdefault(zone, []).append(name)

    positions = {}
    for zone, names in by_zone.items():
        cx, cy = ZONE_CENTERS.get(zone, (0.0, -0.05))
        names = sorted(names)
        n = len(names)
        for i, name in enumerate(names):
            angle = 2 * math.pi * i / max(n, 1)
            positions[name] = (cx + 0.4 * math.cos(angle), cy + 0.4 * math.sin(angle))

    fig = go.Figure()

    for zone, (cx, cy) in ZONE_CENTERS.items():
        fig.add_shape(
            type="circle", xref="x", yref="y",
            x0=cx - 0.65, y0=cy - 0.65, x1=cx + 0.65, y1=cy + 0.65,
            line=dict(color="rgba(140,140,140,0.30)"),
            fillcolor="rgba(140,140,140,0.06)",
        )
        fig.add_annotation(
            x=cx, y=cy + 0.75, text=ZONE_LABELS.get(zone, zone),
            showarrow=False, font=dict(size=13, color="gray"),
        )

    for _, row in tx_day.iterrows():
        a = row["agent"]
        if a not in positions:
            continue
        x0, y0 = positions[a]
        target = row.get("target_agent")
        if row["action"] != "do_nothing" and target in positions:
            x1, y1 = positions[target]
            fig.add_annotation(
                x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=3, arrowsize=1.1, arrowwidth=2,
                arrowcolor="rgba(91, 141, 239, 0.75)", standoff=18, startstandoff=18,
            )
        dm_target = row.get("dm_target")
        if row.get("private_message") and dm_target in positions:
            x1, y1 = positions[dm_target]
            fig.add_annotation(
                x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=3, arrowsize=1.1, arrowwidth=2,
                arrowcolor="rgba(155, 89, 182, 0.8)", standoff=18, startstandoff=18,
            )

    xs, ys, texts, colors, sizes = [], [], [], [], []
    for name, (x, y) in positions.items():
        status = status_by_agent.get(name, "ok")
        style = STATUS_STYLE.get(status, STATUS_STYLE["ok"])
        icon = ROLE_ICONS.get(agent_role_map.get(name), "🧑")
        crown = "👑" if name == leader_name else ""
        xs.append(x); ys.append(y)
        texts.append(f"{crown}{icon} {name}")
        colors.append(style["accent"])
        sizes.append(22 if status == "dead" else 30)

    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=texts, textposition="bottom center",
        marker=dict(size=sizes, color=colors, line=dict(width=2, color="white")),
        hoverinfo="text", showlegend=False,
    ))

    fig.update_layout(
        height=480, margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(visible=False, range=[-2, 2]),
        yaxis=dict(visible=False, range=[-2, 2]),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def format_event(row) -> str:
    """Turns one transaction row into a plain-English sentence for the story feed."""
    action = row["action"]
    if action == "do_nothing":
        line = f"{row['agent']} did nothing this round."
    elif action == "trade":
        price = f" @ {row['price_per_unit']}g/unit" if row.get("price_per_unit") not in (None, "") else ""
        line = f"{row['agent']} traded {row['amount']} {row['resource']} to {row['target_agent']}{price}."
    elif action == "issue_debt":
        line = f"{row['agent']} issued a debt note worth {row['amount']} to {row['target_agent']}."
    elif action == "buy_futures":
        line = f"{row['agent']} bought a futures contract on {row['amount']} {row['resource']}."
    else:
        line = f"{row['agent']} performed {action}."

    if row.get("public_message"):
        line += f' 📣 announced: "{row["public_message"]}"'
    if row.get("private_message") and row.get("dm_target"):
        line += f' 🤫 whispered to {row["dm_target"]}: "{row["private_message"]}"'

    stance = row.get("stance")
    if stance and stance != "none" and row.get("stance_target"):
        stance_text = {
            "endorse": f'👍 endorsed {row["stance_target"]} for leader.',
            "denounce": f'👎 denounced {row["stance_target"]} publicly.',
            "boycott": f'🚫 declared a boycott against {row["stance_target"]}.',
            "propose_alliance": f'🤝 proposed an alliance with {row["stance_target"]}.',
            "vote_leader": f'🗳️ voted for {row["stance_target"]} as town leader.',
        }.get(stance)
        if stance_text:
            line += f" {stance_text}"
    return line


def build_dm_threads(tx: pd.DataFrame) -> list[tuple[tuple[str, str], pd.DataFrame]]:
    """Groups private messages into one thread per unordered (agent, dm_target) pair,
    each already sorted chronologically (tx is loaded ordered by id). Threads are
    returned most-recently-active first, like an inbox.
    """
    dms = tx[tx["private_message"].notna() & (tx["private_message"] != "") & tx["dm_target"].notna()]
    threads: dict[tuple[str, str], list] = {}
    for _, row in dms.iterrows():
        pair = tuple(sorted([row["agent"], row["dm_target"]]))
        threads.setdefault(pair, []).append(row)
    return sorted(threads.items(), key=lambda item: item[1][-1]["id"], reverse=True)


st.markdown(CARD_CSS, unsafe_allow_html=True)


@st.cache_data(ttl=5)
def load_tables(db_path: str):
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(db_path)
    tables = {
        "transactions": pd.read_sql_query("SELECT * FROM transactions ORDER BY id", conn),
        "agent_states": pd.read_sql_query("SELECT * FROM agent_states ORDER BY id", conn),
        "prices": pd.read_sql_query("SELECT * FROM prices ORDER BY id", conn),
        "crisis_events": pd.read_sql_query("SELECT * FROM crisis_events ORDER BY id", conn),
        "deaths": pd.read_sql_query("SELECT * FROM deaths ORDER BY id", conn),
    }
    conn.close()
    return tables


st.title("🏚️ Economy Town — post-apocalyptic economy simulator")
st.caption("Live simulation state from economy.db. Refresh the page after a new run of main.py.")

data = load_tables(str(DB_PATH))

if data is None or data["transactions"].empty:
    st.warning("economy.db has no data yet. Run `python3 main.py` to generate the first run.")
    st.stop()

tx, states, prices, crises, deaths = (
    data["transactions"], data["agent_states"], data["prices"], data["crisis_events"], data["deaths"]
)

status_line = live_status_line(tx)
if status_line:
    st.caption(status_line)

last_round = int(states["round"].max())
latest_states = states[states["round"] == last_round].copy()
latest_states["resources"] = latest_states["resources_json"].apply(json.loads)

agent_role_map = dict(zip(tx["agent"], tx["role"]))
leader = compute_leader(tx)
leader_name = leader[0] if leader else None
alliances = compute_alliances(tx)
boycotts = compute_boycotts(tx)

_last_phase, _last_day = phase_and_day(last_round)
st.subheader(f"Town state — Day {_last_day}, {_last_phase}")
if leader:
    st.caption(f"👑 Current leader: **{leader_name}** ({leader[1]} vote{'s' if leader[1] != 1 else ''})")
cols = st.columns(len(latest_states))
for col, (_, row) in zip(cols, latest_states.iterrows()):
    with col:
        st.markdown(
            agent_card_html(row["agent"], row["role"], row["status"], row["resources"], is_leader=(row["agent"] == leader_name)),
            unsafe_allow_html=True,
        )

st.divider()

st.subheader("🗺️ Town map")
st.caption(
    "Top-down view of who's where and who did what with whom, phase by phase. "
    "Blue arrow = trade/debt/futures, purple arrow = private DM. Drag the slider to scrub through time."
)
all_rounds = sorted(tx["round"].unique())
if len(all_rounds) == 1:
    round_choice = all_rounds[0]
    phase_label, day_number = phase_and_day(round_choice)
    st.caption(f"Only Day {day_number}, {phase_label} so far.")
else:
    round_choice = st.select_slider(
        "Moment", options=all_rounds,
        value=all_rounds[-1],
        format_func=lambda r: f"Day {phase_and_day(r)[1]} · {phase_and_day(r)[0]}",
        key="town_map_moment",
    )
tx_day = tx[tx["round"] == round_choice]
day_states = states[states["round"] == round_choice]
status_by_agent = dict(zip(day_states["agent"], day_states["status"]))
location_by_agent = dict(zip(tx_day["agent"], tx_day["location"]))
st.plotly_chart(
    build_town_map(tx_day, agent_role_map, status_by_agent, location_by_agent, leader_name),
    width="stretch", config={"displayModeBar": False},
)

st.divider()

st.subheader("🏛️ Town politics")
st.caption("Elections, endorsements, denouncements, alliances, and boycotts.")

p1, p2 = st.columns([2, 3])

with p1:
    st.markdown("**Leader votes (all-time)**")
    votes = tx[tx["stance"] == "vote_leader"]["stance_target"].value_counts()
    if votes.empty:
        st.info("No votes cast yet.")
    else:
        st.bar_chart(votes)

    st.markdown("**Alliances**")
    if not alliances:
        st.info("No alliances formed yet.")
    else:
        for pair in alliances:
            a, b = tuple(pair)
            st.markdown(f"🤝 **{a}** ↔ **{b}**")

    st.markdown("**Active boycotts**")
    if not boycotts:
        st.info("No boycotts declared yet.")
    else:
        for pair in boycotts:
            a, b = tuple(pair)
            st.markdown(f"🚫 **{a}** ↔ **{b}** (trades between them now fail)")

with p2:
    st.markdown("**Endorsements & denouncements**")
    political = tx[tx["stance"].isin(["endorse", "denounce"])]
    if political.empty:
        st.info("No public endorsements or denouncements yet.")
    else:
        for _, row in political.iloc[::-1].iterrows():
            icon = "👍" if row["stance"] == "endorse" else "👎"
            verb = "endorsed" if row["stance"] == "endorse" else "denounced"
            st.markdown(
                event_card_html(
                    f"{icon} Round {row['round']}: <b>{row['agent']}</b> {verb} <b>{row['stance_target']}</b>",
                    "#5b8def" if row["stance"] == "endorse" else "#e74c3c",
                    "rgba(91, 141, 239, 0.10)" if row["stance"] == "endorse" else "rgba(231, 76, 60, 0.10)",
                ),
                unsafe_allow_html=True,
            )

st.divider()

st.subheader("🤫 Direct messages")
st.caption("Private one-on-one conversations — never shown to the rest of the town.")

relationship_fig = build_relationship_graph(tx, agent_role_map, alliances, boycotts)
if relationship_fig is not None:
    st.markdown("**Who's connected to whom** — blue = DMs (thickness = volume), green = alliance, red dashed = boycott")
    st.plotly_chart(relationship_fig, width="stretch", config={"displayModeBar": False})

dm_threads = build_dm_threads(tx)
if not dm_threads:
    st.info("No private conversations yet.")
else:
    thread_labels = []
    for pair, msgs in dm_threads:
        a, b = pair
        icon_a = ROLE_ICONS.get(agent_role_map.get(a), "🧑")
        icon_b = ROLE_ICONS.get(agent_role_map.get(b), "🧑")
        last_msg = msgs[-1]["private_message"]
        preview = (last_msg[:44] + "…") if len(last_msg) > 44 else last_msg
        thread_labels.append(f'{icon_a} {a} ↔ {icon_b} {b}  ·  {len(msgs)} msg  ·  "{preview}"')

    chosen = st.selectbox(
        "Conversation", range(len(thread_labels)), format_func=lambda i: thread_labels[i], key="dm_thread_select"
    )
    pair, msgs = dm_threads[chosen]
    left_agent = pair[0]

    bubbles_html = ""
    for row in msgs:
        side = "left" if row["agent"] == left_agent else "right"
        icon = ROLE_ICONS.get(agent_role_map.get(row["agent"]), "🧑")
        bubbles_html += (
            f'<div class="dm-bubble-row {side}">'
            f'<div class="dm-bubble {side}">'
            f'<div class="dm-meta">{icon} {row["agent"]} · round {row["round"]}</div>'
            f'{row["private_message"]}'
            f"</div></div>"
        )
    st.markdown(bubbles_html, unsafe_allow_html=True)

st.divider()

left, right = st.columns([3, 2])

with left:
    st.subheader("💰 Price dynamics")
    price_pivot = prices.pivot(index="round", columns="resource", values="price")
    st.line_chart(price_pivot)

    st.subheader("📦 Agent resources by round")
    resource_choice = st.selectbox(
        "Resource", ["food", "water", "gold", "debt_note"], key="resource_select"
    )
    states_expanded = states.copy()
    states_expanded["resources"] = states_expanded["resources_json"].apply(json.loads)
    states_expanded[resource_choice] = states_expanded["resources"].apply(
        lambda r: r.get(resource_choice, 0)
    )
    resource_pivot = states_expanded.pivot(index="round", columns="agent", values=resource_choice)
    st.line_chart(resource_pivot)

with right:
    st.subheader("⚠️ Crisis events")
    if crises.empty:
        st.info("No crises yet.")
    else:
        for _, row in crises.iterrows():
            st.markdown(
                event_card_html(f"<b>Round {row['round']}</b> — {row['description']}", "#e74c3c", "rgba(231, 76, 60, 0.10)"),
                unsafe_allow_html=True,
            )

    st.subheader("💀 Death log")
    if deaths.empty:
        st.info("Everyone is still alive.")
    else:
        for _, row in deaths.iterrows():
            st.markdown(
                event_card_html(
                    f"<b>Round {row['round']}</b> — {row['agent']} ({row['role']}): {row['cause']}",
                    "#7f8c8d", "rgba(127, 140, 141, 0.14)",
                ),
                unsafe_allow_html=True,
            )

st.divider()
st.subheader("📊 Economic analytics")
st.caption("Derived metrics for the analyst view: inequality, inflation, and the credit market.")

price_pivot_all = prices.pivot(index="round", columns="resource", values="price")

a1, a2, a3 = st.columns(3)

with a1:
    st.markdown("**Wealth inequality (Gini)**")
    wealth_df = wealth_by_round(states, price_pivot_all)
    gini_series = wealth_df.groupby("round")["wealth"].apply(lambda s: gini_coefficient(s.tolist()))
    st.line_chart(gini_series)
    st.caption(f"Latest: **{gini_series.iloc[-1]:.2f}** · 0 = perfectly equal, 1 = one person has everything.")

with a2:
    st.markdown("**Cumulative inflation since round 1**")
    inflation_pct = (price_pivot_all - price_pivot_all.iloc[0]) / price_pivot_all.iloc[0] * 100
    st.line_chart(inflation_pct)
    latest_inflation = inflation_pct.iloc[-1]
    st.caption(" · ".join(f"{res}: {val:+.0f}%" for res, val in latest_inflation.items()))

with a3:
    st.markdown("**Credit market (debt_note)**")
    debt_issued = tx[tx["action"] == "issue_debt"].groupby("round")["amount"].sum()
    if debt_issued.empty:
        st.info("No debt issued yet.")
    else:
        st.bar_chart(debt_issued)
    debt_balances = latest_states[["agent", "role"]].copy()
    debt_balances["debt_note"] = latest_states["resources"].apply(lambda r: r.get("debt_note", 0))
    debt_balances = debt_balances.sort_values("debt_note", ascending=False)
    if not debt_balances.empty:
        top_creditor = debt_balances.iloc[0]
        top_debtor = debt_balances.iloc[-1]
        st.caption(
            f"Top creditor: **{top_creditor['agent']}** ({top_creditor['debt_note']:+.1f}) · "
            f"Top debtor: **{top_debtor['agent']}** ({top_debtor['debt_note']:+.1f})"
        )

st.divider()
st.subheader("📖 Story feed")
st.caption("A readable, phase-by-phase recap of everything that happened — script material for posts.")
for rnd in sorted(tx["round"].unique(), reverse=True):
    round_tx = tx[tx["round"] == rnd]
    round_crises = crises[crises["round"] == rnd]
    round_deaths = deaths[deaths["round"] == rnd]
    phase_label, day_number = phase_and_day(rnd)
    with st.expander(f"Day {day_number} · {phase_label}", expanded=(rnd == last_round)):
        for _, crow in round_crises.iterrows():
            st.markdown(f"⚠️ **{crow['description']}**")
        for _, drow in round_deaths.iterrows():
            st.markdown(f"💀 **{drow['agent']} ({drow['role']}) died** — {drow['cause']}")
        for _, row in round_tx.iterrows():
            st.markdown(f"- {format_event(row)}")

st.divider()
st.subheader("📜 Transaction log")
round_filter = st.multiselect(
    "Filter by round", sorted(tx["round"].unique()), default=sorted(tx["round"].unique())
)
st.dataframe(
    tx[tx["round"].isin(round_filter)].drop(columns=["id"]),
    width="stretch",
    hide_index=True,
)
