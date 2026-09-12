from __future__ import annotations
import json
import os
import re
from typing import Any
import requests

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

# Railway/Linux environment variable names are case-sensitive. Accept the
# canonical name plus common aliases so a valid key is not missed simply
# because the variable name was entered slightly differently.
_KEY_ALIASES = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_KEY",
    "DEEPSEEK_APIKEY",
    "DEEPSEEK_TOKEN",
    "DEEPSEEK_API_TOKEN",
)

def _clean_env_value(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if "=" in value and value.split("=", 1)[0].strip().upper() in _KEY_ALIASES:
        value = value.split("=", 1)[1].strip()
    return value

def _normalized_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(name).upper()).strip("_")

def api_key_info() -> tuple[str, str | None]:
    for name in _KEY_ALIASES:
        key = _clean_env_value(os.getenv(name))
        if key:
            return key, name
    wanted = {_normalized_name(x) for x in _KEY_ALIASES}
    for name, value in os.environ.items():
        if _normalized_name(name) in wanted:
            key = _clean_env_value(value)
            if key:
                return key, name
    return "", None

def api_key_value() -> str:
    return api_key_info()[0]

def api_key_source() -> str | None:
    return api_key_info()[1]

def configured() -> bool:
    return bool(api_key_value())

def model_name() -> str:
    value = _clean_env_value(os.getenv("DEEPSEEK_MODEL"))
    return value or DEFAULT_MODEL

def base_url() -> str:
    value = _clean_env_value(os.getenv("DEEPSEEK_BASE_URL"))
    return (value or DEFAULT_BASE_URL).rstrip("/")


def _post_result(messages: list[dict[str, Any]], *, temperature: float = 0.15, max_tokens: int = 2200, json_mode: bool = False) -> dict[str, Any]:
    key = api_key_value()
    if not key:
        raise RuntimeError("DeepSeek API key is not configured in Railway Variables")
    payload: dict[str, Any] = {
        "model": model_name(), "messages": messages, "temperature": temperature,
        "max_tokens": max_tokens, "stream": False, "thinking": {"type": "disabled"},
    }
    if json_mode:
        payload["response_format"]={"type":"json_object"}
    resp=requests.post(base_url()+"/chat/completions",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=payload,timeout=90)
    resp.raise_for_status()
    obj=resp.json(); choices=obj.get("choices") or []
    if not choices:
        return {"text":"","finish_reason":"missing_choice","usage":obj.get("usage") or {}}
    ch=choices[0] or {}; msg=ch.get("message") or {}
    return {"text":(msg.get("content") or "").strip(),"finish_reason":ch.get("finish_reason"),"usage":obj.get("usage") or {}}

def _post(messages: list[dict[str, Any]], *, temperature: float = 0.15, max_tokens: int = 2200, json_mode: bool = False) -> str:
    return _post_result(messages,temperature=temperature,max_tokens=max_tokens,json_mode=json_mode)["text"]


def _missing_explanation_parts(text: str, kind: str="general") -> list[str]:
    t=(text or "").strip()
    if kind=="baseline":
        checks=[
            ("风险结果", ("综合风险","风险指数","风险值","当前风险")),
            ("重点供应地", ("重点供应地","最大贡献供应地","供应地","节点")),
            ("主要风险来源", ("主要风险来源","长期缺水","历史干旱","季节性")),
            ("数据说明", ("数据说明","代理","假设","缺口","可信","覆盖")),
            ("管理建议", ("管理建议","建议","优先","应当","可以")),
        ]
    elif kind=="scenario":
        checks=[
            ("变化结果", ("变化结果","变化","供应损失","未满足需求","风险")),
            ("重点供应地", ("供应地","节点","受影响")),
            ("主要变化来源", ("主要变化","原因","来源","中断","干旱","压力")),
            ("数据说明", ("数据说明","假设","参数","可信","演示")),
            ("管理建议", ("管理建议","建议","优先","应当","可以")),
        ]
    else:
        return [] if len(t)>=40 else ["完整回答"]
    missing=[]
    for label,alts in checks:
        if not any(x in t for x in alts):
            missing.append(label)
    if len(t)<120 and kind in {"baseline","scenario"}:
        missing.append("完整篇幅")
    return list(dict.fromkeys(missing))

def _looks_complete(text: str, kind: str="general") -> bool:
    return not _missing_explanation_parts(text,kind)

def chat(system_prompt: str, user_prompt: str, fallback: str) -> tuple[str, dict[str, Any]]:
    if not configured():
        return fallback,{"provider":"local_fallback","model":None,"used":False,"complete":True}
    try:
        res=_post_result([{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],max_tokens=2200)
        text=_plain_user_language(res.get("text") or "")
        if res.get("finish_reason")=="length" or not _looks_complete(text):
            res=_post_result([{"role":"system","content":system_prompt},{"role":"user","content":user_prompt+"\n\n请完整回答并自然收尾，不要只写半句。"}],max_tokens=3200)
            text=_plain_user_language(res.get("text") or "")
        if res.get("finish_reason")!="stop" or not _looks_complete(text):
            return fallback,{"provider":"local_fallback","model":model_name(),"used":False,"complete":False,"retryable":True,"finish_reason":res.get("finish_reason"),"error":"AI explanation incomplete"}
        return text,{"provider":"DeepSeek","model":model_name(),"used":True,"complete":True,"finish_reason":res.get("finish_reason")}
    except Exception as exc:
        return fallback,{"provider":"local_fallback","model":model_name(),"used":False,"complete":False,"retryable":True,"error":str(exc)[:300]}


def _json_from_text(raw: str) -> dict[str, Any] | None:
    raw = (raw or "").strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def classify_intent(message: str) -> dict[str, Any] | None:
    """Use DeepSeek only for intent/parameter understanding, never for risk calculation."""
    if not configured() or not (message or "").strip():
        return None
    sys = (
        "你是 WaterPulse 上游供应链水风险 AI Agent 的实时需求识别器。只做意图和参数理解，不计算任何风险数字。"
        "只输出JSON对象，不要Markdown。"
        "intent只能是 analyze、scenario、explain、data_help、export、general。"
        "scenario_type只能是 PeakSeason、AqueductFuture、ExtremeDrought、NodeFailure 或 null。"
        "额外输出 analysis_scope，只能是 general_question、material_reference、company_specific。"
        "字段：material=用户明确提到的原材料原名或null，不限于甘蔗/甜菜/大豆；"
        "location=用户明确提到的供应地区/国家/省州/产区或null；enterprise=企业名或null；"
        "wants_quantitative=true/false；wants_reference=true/false；"
        "year(整数或null)、path(BAU/OPT/PES或null)、failure_fraction(0-1或null)、inventory(0-1或null)。"
        "用户只是问知识、原因、管理办法时也要识别为 explain/general，而不是机械要求文件。"
        "用户没有企业数据但问某原材料/地区风险时，analysis_scope=material_reference，允许后续使用项目参考库做初步判断。"
        "只有用户明确要求企业专属量化结果、提供采购结构或企业资料时，analysis_scope=company_specific。"
        "如果明确问不同压力/中断/未来变化，intent=scenario；如果要求下载报告，intent=export。"
    )
    try:
        raw = _post([
            {"role": "system", "content": sys},
            {"role": "user", "content": message},
        ], temperature=0.0, max_tokens=500, json_mode=True)
        obj = _json_from_text(raw)
        if not obj or obj.get("intent") not in {"analyze", "scenario", "explain", "data_help", "export", "general"}:
            return None
        if obj.get("scenario_type") not in {None, "PeakSeason", "AqueductFuture", "ExtremeDrought", "NodeFailure"}:
            obj["scenario_type"] = None
        return obj
    except Exception:
        return None


def extract_supply_chain(text: str) -> dict[str, Any] | None:
    """Extract candidate enterprise/material/node/procurement fields from report text.
    Output is candidate data only and must be confirmed before deterministic calculation.
    """
    if not configured() or not (text or "").strip():
        return None
    excerpt = text[:45000]
    sys = (
        "你是供应链资料结构化抽取工具。只从用户原文抽取，不猜测、不补齐。"
        "请只输出JSON，不要Markdown。结构：{enterprise:null或字符串, records:[...] }。"
        "每条records字段：material,node_id,node_name,purchase_weight,year,evidence,confidence。"
        "material只在原文明确时填甘蔗/甜菜/大豆或原材料原名；purchase_weight统一为0-1，原文没有就null；"
        "node_id只有原文明确包含项目节点编号时填写，否则null；node_name填写供应地/省州/国家/供应节点原文；"
        "evidence必须是支持该条记录的简短原文片段；confidence只可High/Medium/Low。"
        "不要把国家均值、推测值或常识当作企业采购事实。"
    )
    try:
        raw = _post([
            {"role": "system", "content": sys},
            {"role": "user", "content": "请抽取以下报告中的上游采购/供应链候选信息：\n" + excerpt},
        ], temperature=0.0, max_tokens=2200, json_mode=True)
        obj = _json_from_text(raw)
        if not obj or not isinstance(obj.get("records"), list):
            return None
        return obj
    except Exception:
        return None


def general_guidance(message: str, fallback: str, governance_context: dict[str, Any] | None = None,
                     reference_context: dict[str, Any] | None = None,
                     history: list[dict[str, Any]] | None = None) -> tuple[str, dict[str, Any]]:
    """Embedded first-contact AI: answer the question first, then guide only when useful.

    No enterprise file is required for qualitative Q&A or reference-library exploration.
    """
    if not configured():
        return fallback, {"provider":"local_fallback","model":None,"used":False,"complete":True}

    sys = (
        "你是 WaterPulse，一名真正嵌入产品中的科技型农食企业上游供应链水风险 AI 助手。"
        "每次用户输入都要先理解问题并直接作答，不能无论问什么都回复同一段“请上传文件”。"
        "没有 ESG、采购表或企业数据时，你仍然可以：解释概念、分析风险机制、比较地区或原材料的典型风险、"
        "给出管理思路；如果后台提供 reference_context，还可以基于项目当前参考库做明确标注为“参考性/初步”的分析。"
        "只有当用户明确需要企业专属的精确量化结果时，才在回答问题之后自然说明还需要采购来源、地区和采购占比。"
        "如果项目参考库能支持该原材料或地区，要主动告诉用户可以直接用参考数据先做初步分析，不要求先上传文件。"
        "如果项目参考库不支持该材料/地区，可以继续做定性分析，但必须说明当前没有可核验的项目量化数据，不能编造精确数字。"
        "如果用户提到企业名称但没有采购结构，不得猜该企业真实供应商或采购比例；可以分析行业层面的风险，并说明如何进一步企业化。"
        "不要把“上传 ESG 报告”当成唯一入口；它只是获取企业采购信息的一种方式。"
        "不要声称你有实时联网搜索或最新公开数据库，除非 reference_context 明确给出了数据。"
        "面向普通用户始终使用自然中文，不出现 Baseline、Scenario、PRWI、WS、DR、SV、BWD、DYS、CTS、OA、"
        "JSON、Schema、字段合同、工具调用、工作流、确定性引擎等后台术语。"
        "回答必须针对当前问题变化，优先给结论/解释，再给下一步选项；不要使用固定模板重复同一段话。"
        "不要凭空生成企业采购比例、地点风险分值、综合风险数值或财务损失。"
    )

    context_parts=[]
    if reference_context:
        context_parts.append(
            "以下是项目当前可核验的参考库上下文。只能基于这些事实做项目数据层面的表述；"
            "若字段 status 表示未匹配，不得假装已匹配：\n"
            + json.dumps(reference_context, ensure_ascii=False, default=str)
        )
    if governance_context:
        context_parts.append(
            "以下是后台数据要求摘要，只用于判断什么时候需要补企业信息；不要向用户照搬内部字段名：\n"
            + json.dumps(governance_context, ensure_ascii=False, default=str)
        )

    messages=[{"role":"system","content":sys}]
    for item in (history or [])[-8:]:
        role=item.get("role")
        content=str(item.get("content") or "").strip()
        if role in {"user","assistant"} and content:
            messages.append({"role":role,"content":content[:5000]})
    user_content=message
    if context_parts:
        user_content += "\n\n[后台参考上下文，仅供你作答使用]\n" + "\n\n".join(context_parts)
    messages.append({"role":"user","content":user_content})

    try:
        res=_post_result(messages, temperature=0.25, max_tokens=2400)
        text=_plain_user_language(res.get("text") or "")
        if res.get("finish_reason")=="length" or not _looks_complete(text):
            messages[-1]["content"] += "\n\n请把当前问题完整回答完，先回答问题，不要机械重复上传资料的提示。"
            res=_post_result(messages, temperature=0.15, max_tokens=3400)
            text=_plain_user_language(res.get("text") or "")
        if res.get("finish_reason")!="stop" or not _looks_complete(text):
            return fallback,{"provider":"local_fallback","model":model_name(),"used":False,"complete":False,
                             "retryable":True,"finish_reason":res.get("finish_reason"),"error":"AI answer incomplete"}
        return text,{"provider":"DeepSeek","model":model_name(),"used":True,"complete":True,
                     "finish_reason":res.get("finish_reason")}
    except Exception as exc:
        return fallback,{"provider":"local_fallback","model":model_name(),"used":False,"complete":False,
                         "retryable":True,"error":str(exc)[:300]}


def _compact_tool_payload(baseline: dict|None, scenario: dict|None, validation: dict|None, runtime_context: dict|None) -> dict[str, Any]:
    out={"runtime_context":runtime_context or {},"validation":validation or {}}
    if baseline:
        bd=baseline.get("data") or {}; summary=bd.get("summary") or []
        if hasattr(summary,"to_dict"): summary=summary.to_dict(orient="records")
        nodes=bd.get("nodes") or []
        if hasattr(nodes,"to_dict"): nodes=nodes.to_dict(orient="records")
        if isinstance(nodes,list): nodes=sorted(nodes,key=lambda x:float(x.get("C") or -1),reverse=True)[:6]
        out["current_risk"]={
            "status":baseline.get("status"),"summary":summary,"top_nodes":nodes,
            "warnings":baseline.get("warnings") or [],"proxy_fields":baseline.get("proxy_fields") or [],
            "assumptions":baseline.get("assumptions") or [],"source_refs":baseline.get("source_refs") or [],
            "data_identity":baseline.get("data_identity") or {},
        }
    if scenario:
        sd=scenario.get("data") or {}; clean={}
        for k,v in sd.items():
            if k in {"node_table","replacement_table"} and hasattr(v,"to_dict"): v=v.to_dict(orient="records")
            clean[k]=(v[:6] if isinstance(v,list) else v)
        out["comparison"]={"status":scenario.get("status"),"data":clean,"warnings":scenario.get("warnings") or []}
    return out

def analyze_tool_result(*, user_question: str, baseline: dict | None = None, scenario: dict | None = None,
                        validation: dict | None = None, runtime_context: dict|None=None, fallback: str = "") -> tuple[str, dict[str, Any]]:
    if not configured(): return fallback,{"provider":"local_fallback","model":None,"used":False,"complete":True}
    payload=_compact_tool_payload(baseline,scenario,validation,runtime_context); payload["user_question"]=user_question
    kind="scenario" if scenario else "baseline"
    sys=(
        "你是 WaterPulse 上游供应链水风险决策助手。runtime_context 是本次真实运行状态，优先级最高；绝不能说没有收到文件、没有识别记录，除非 runtime_context 明确这样写。"
        "你只能解释给定的计算结果，不能重新计算或修改任何数值。没有的数字就说未提供，绝对不要猜。"
        "每次成功解释必须完整包含五个企业可读部分，并使用这些小标题：风险结论、重点供应地、主要风险来源、数据可信度与限制、管理建议。"
        "风险结果必须说明数值及其含义；重点供应地必须指出最大贡献节点；主要风险来源必须对应计算得到的贡献；"
        "数据说明必须说明未知份额、代理值、假设或置信度（没有也要明确说未发现）；管理建议必须与结果对应。"
        "如果是不同情况比较，则用“变化结果、重点供应地、主要变化来源、数据说明、管理建议”，并说清供应含义。"
        "面向普通用户，不要出现 Baseline、Scenario、PRWI、WS、DR、SV、BWD、DYS、CTS、OA、JSON、Schema 等内部术语。"
        "控制在 250-650 字，句子必须写完整并自然收尾。"
    )
    raw_payload=json.dumps(payload,ensure_ascii=False,default=str)
    try:
        messages=[{"role":"system","content":sys},{"role":"user","content":raw_payload}]
        res=_post_result(messages,temperature=0.1,max_tokens=1800); text=_plain_user_language(res.get("text") or "")
        if res.get("finish_reason")=="length" or not _looks_complete(text,kind):
            messages[-1]["content"] += "\n\n上一版可能不完整。请严格按五项要求完整输出，最后必须给出完整管理建议，不要半句结束。"
            res=_post_result(messages,temperature=0.05,max_tokens=2800); text=_plain_user_language(res.get("text") or "")
        if res.get("finish_reason")!="stop" or not _looks_complete(text,kind):
            missing=_missing_explanation_parts(text,kind)
            return fallback,{"provider":"local_fallback","model":model_name(),"used":False,"complete":False,"retryable":True,
                             "finish_reason":res.get("finish_reason"),"error":"AI explanation incomplete or truncated",
                             "missing_parts":missing}
        return text,{"provider":"DeepSeek","model":model_name(),"used":True,"complete":True,"finish_reason":res.get("finish_reason")}
    except Exception as exc:
        return fallback,{"provider":"local_fallback","model":model_name(),"used":False,"complete":False,"retryable":True,"error":str(exc)[:300]}


def connection_test() -> dict[str, Any]:
    """Make a minimal live API call without ever returning the secret itself."""
    source = api_key_source()
    if not configured():
        return {
            "ok": False,
            "configured": False,
            "env_source": None,
            "model": model_name(),
            "base_url": base_url(),
            "message": "No DeepSeek key was found in the service environment.",
        }
    try:
        text = _post([
            {"role": "system", "content": "You are a connection test. Reply with exactly OK."},
            {"role": "user", "content": "ping"},
        ], temperature=0.0, max_tokens=8)
        return {
            "ok": True,
            "configured": True,
            "env_source": source,
            "model": model_name(),
            "base_url": base_url(),
            "reply": text[:50],
        }
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        body = ""
        try:
            body = (exc.response.text or "")[:300]
        except Exception:
            pass
        return {
            "ok": False,
            "configured": True,
            "env_source": source,
            "model": model_name(),
            "base_url": base_url(),
            "http_status": status,
            "message": body or str(exc)[:300],
        }
    except Exception as exc:
        return {
            "ok": False,
            "configured": True,
            "env_source": source,
            "model": model_name(),
            "base_url": base_url(),
            "message": str(exc)[:500],
        }
