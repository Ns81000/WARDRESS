/*
 * Provider id -> bundled same-origin brand mark. Keys are spelled EXACTLY
 * as the models.dev catalog ids (`fireworks-ai`, `zhipuai`,
 * `tencent-tokenhub`, ...) plus the two sentinel types. Every asset was
 * vendored at build time from public brand-SVG libraries (the same
 * full-color sources the pre-Phase-27 UI fetched at runtime) and
 * normalized for <img> context. The app never fetches provider imagery
 * at runtime; catalog providers without a vendored file fall back to the
 * local letter avatar — never a network fetch.
 */

import zhipuaiLogo from "@/assets/providers/zhipuai.svg"
import anyapiLogo from "@/assets/providers/anyapi.png"
import tencent_tokenhubLogo from "@/assets/providers/tencent-tokenhub.png"
import fireworks_aiLogo from "@/assets/providers/fireworks-ai.png"
import wandbLogo from "@/assets/providers/wandb.svg"
import crossmodelLogo from "@/assets/providers/crossmodel.png"
import claudinioLogo from "@/assets/providers/claudinio.png"
import snowflake_cortexLogo from "@/assets/providers/snowflake-cortex.png"
import cohereLogo from "@/assets/providers/cohere.svg"
import opencode_goLogo from "@/assets/providers/opencode-go.png"
import poeLogo from "@/assets/providers/poe.svg"
import basetenLogo from "@/assets/providers/baseten.png"
import nvidiaLogo from "@/assets/providers/nvidia.svg"
import nebiusLogo from "@/assets/providers/nebius.png"
import vivgridLogo from "@/assets/providers/vivgrid.png"
import googleLogo from "@/assets/providers/google.svg"
import thinkingmachinesLogo from "@/assets/providers/thinkingmachines.png"
import lilacLogo from "@/assets/providers/lilac.png"
import zhipuai_coding_planLogo from "@/assets/providers/zhipuai-coding-plan.png"
import nano_gptLogo from "@/assets/providers/nano-gpt.png"
import fastrouterLogo from "@/assets/providers/fastrouter.png"
import nearaiLogo from "@/assets/providers/nearai.png"
import daoxeLogo from "@/assets/providers/daoxe.png"
import crofLogo from "@/assets/providers/crof.png"
import abliteration_aiLogo from "@/assets/providers/abliteration-ai.png"
import alibaba_coding_plan_cnLogo from "@/assets/providers/alibaba-coding-plan-cn.png"
import llmgatewayLogo from "@/assets/providers/llmgateway.png"
import kenariLogo from "@/assets/providers/kenari.png"
import friendliLogo from "@/assets/providers/friendli.png"
import opencodeLogo from "@/assets/providers/opencode.svg"
import sakanaLogo from "@/assets/providers/sakana.png"
import trustedrouterLogo from "@/assets/providers/trustedrouter.png"
import atomic_chatLogo from "@/assets/providers/atomic-chat.png"
import inceptionLogo from "@/assets/providers/inception.png"
import cloudflare_workers_aiLogo from "@/assets/providers/cloudflare-workers-ai.png"
import modelscopeLogo from "@/assets/providers/modelscope.svg"
import github_copilotLogo from "@/assets/providers/github-copilot.svg"
import p302aiLogo from "@/assets/providers/302ai.png"
import heliconeLogo from "@/assets/providers/helicone.png"
import alibaba_coding_planLogo from "@/assets/providers/alibaba-coding-plan.png"
import submodelLogo from "@/assets/providers/submodel.png"
import neonLogo from "@/assets/providers/neon.svg"
import ambientLogo from "@/assets/providers/ambient.png"
import privatemode_aiLogo from "@/assets/providers/privatemode-ai.png"
import unorouterLogo from "@/assets/providers/unorouter.png"
import frogbotLogo from "@/assets/providers/frogbot.png"
import the_grid_aiLogo from "@/assets/providers/the-grid-ai.png"
import sap_ai_coreLogo from "@/assets/providers/sap-ai-core.png"
import upstageLogo from "@/assets/providers/upstage.svg"
import cline_passLogo from "@/assets/providers/cline-pass.png"
import regolo_aiLogo from "@/assets/providers/regolo-ai.png"
import aiandLogo from "@/assets/providers/aiand.png"
import pioneerLogo from "@/assets/providers/pioneer.png"
import siliconflowLogo from "@/assets/providers/siliconflow.png"
import ai_routerLogo from "@/assets/providers/ai-router.png"
import zenmuxLogo from "@/assets/providers/zenmux.svg"
import inferenceLogo from "@/assets/providers/inference.svg"
import evrocLogo from "@/assets/providers/evroc.png"
import abacusLogo from "@/assets/providers/abacus.png"
import empiriolabsLogo from "@/assets/providers/empiriolabs.png"
import alibaba_token_planLogo from "@/assets/providers/alibaba-token-plan.png"
import metaLogo from "@/assets/providers/meta.svg"
import azure_cognitive_servicesLogo from "@/assets/providers/azure-cognitive-services.svg"
import wafer_aiLogo from "@/assets/providers/wafer.ai.png"
import clarifaiLogo from "@/assets/providers/clarifai.svg"
import iflowcnLogo from "@/assets/providers/iflowcn.png"
import gitlabLogo from "@/assets/providers/gitlab.svg"
import veniceLogo from "@/assets/providers/venice.png"
import scalewayLogo from "@/assets/providers/scaleway.svg"
import togetheraiLogo from "@/assets/providers/togetherai.svg"
import digitaloceanLogo from "@/assets/providers/digitalocean.svg"
import moonshotai_cnLogo from "@/assets/providers/moonshotai-cn.svg"
import lmstudioLogo from "@/assets/providers/lmstudio.png"
import ovhcloudLogo from "@/assets/providers/ovhcloud.svg"
import zeldocLogo from "@/assets/providers/zeldoc.png"
import aurikoLogo from "@/assets/providers/auriko.png"
import azureLogo from "@/assets/providers/azure.svg"
import qihang_aiLogo from "@/assets/providers/qihang-ai.png"
import bergetLogo from "@/assets/providers/berget.png"
import google_vertex_anthropicLogo from "@/assets/providers/google-vertex-anthropic.png"
import moarkLogo from "@/assets/providers/moark.png"
import novaLogo from "@/assets/providers/nova.png"
import vultrLogo from "@/assets/providers/vultr.svg"
import io_netLogo from "@/assets/providers/io-net.png"
import neuralwattLogo from "@/assets/providers/neuralwatt.png"
import aki_ioLogo from "@/assets/providers/aki-io.png"
import xaiLogo from "@/assets/providers/xai.svg"
import hetznerLogo from "@/assets/providers/hetzner.svg"
import zenifraLogo from "@/assets/providers/zenifra.png"
import aihubmixLogo from "@/assets/providers/aihubmix.svg"
import morphLogo from "@/assets/providers/morph.svg"
import umans_ai_coding_planLogo from "@/assets/providers/umans-ai-coding-plan.png"
import mistralLogo from "@/assets/providers/mistral.svg"
import umans_aiLogo from "@/assets/providers/umans-ai.png"
import ofoxLogo from "@/assets/providers/ofox.png"
import orcarouterLogo from "@/assets/providers/orcarouter.png"
import xiaomi_token_plan_cnLogo from "@/assets/providers/xiaomi-token-plan-cn.png"
import v0Logo from "@/assets/providers/v0.svg"
import poolsideLogo from "@/assets/providers/poolside.png"
import routing_runLogo from "@/assets/providers/routing-run.png"
import google_vertexLogo from "@/assets/providers/google-vertex.svg"
import tencent_token_planLogo from "@/assets/providers/tencent-token-plan.png"
import syntheticLogo from "@/assets/providers/synthetic.png"
import zai_coding_planLogo from "@/assets/providers/zai-coding-plan.png"
import gmicloudLogo from "@/assets/providers/gmicloud.png"
import freemodelLogo from "@/assets/providers/freemodel.png"
import amazon_bedrockLogo from "@/assets/providers/amazon-bedrock.png"
import xiaomi_token_plan_amsLogo from "@/assets/providers/xiaomi-token-plan-ams.png"
import minimaxLogo from "@/assets/providers/minimax.png"
import groqLogo from "@/assets/providers/groq.svg"
import deepseekLogo from "@/assets/providers/deepseek.svg"
import kimi_for_codingLogo from "@/assets/providers/kimi-for-coding.png"
import requestyLogo from "@/assets/providers/requesty.png"
import llamaLogo from "@/assets/providers/llama.png"
import kiloLogo from "@/assets/providers/kilo.png"
import merge_gatewayLogo from "@/assets/providers/merge-gateway.png"
import subconsciousLogo from "@/assets/providers/subconscious.png"
import tencent_coding_planLogo from "@/assets/providers/tencent-coding-plan.png"
import alibabaLogo from "@/assets/providers/alibaba.svg"
import github_modelsLogo from "@/assets/providers/github-models.png"
import vercelLogo from "@/assets/providers/vercel.svg"
import alibaba_cnLogo from "@/assets/providers/alibaba-cn.png"
import novita_aiLogo from "@/assets/providers/novita-ai.png"
import openrouterLogo from "@/assets/providers/openrouter.svg"
import huggingfaceLogo from "@/assets/providers/huggingface.svg"
import minimax_coding_planLogo from "@/assets/providers/minimax-coding-plan.png"
import siliconflow_cnLogo from "@/assets/providers/siliconflow-cn.png"
import tinfoilLogo from "@/assets/providers/tinfoil.png"
import xiaomiLogo from "@/assets/providers/xiaomi.svg"
import stackitLogo from "@/assets/providers/stackit.png"
import deepinfraLogo from "@/assets/providers/deepinfra.svg"
import anthropicLogo from "@/assets/providers/anthropic.svg"
import cloudflare_ai_gatewayLogo from "@/assets/providers/cloudflare-ai-gateway.png"
import lynkrLogo from "@/assets/providers/lynkr.png"
import alibaba_token_plan_cnLogo from "@/assets/providers/alibaba-token-plan-cn.png"
import stepfun_aiLogo from "@/assets/providers/stepfun-ai.svg"
import chutesLogo from "@/assets/providers/chutes.png"
import cerebrasLogo from "@/assets/providers/cerebras.svg"
import qiniu_aiLogo from "@/assets/providers/qiniu-ai.svg"
import longcatLogo from "@/assets/providers/longcat.svg"
import ollama_cloudLogo from "@/assets/providers/ollama-cloud.png"
import jiekouLogo from "@/assets/providers/jiekou.png"
import perplexityLogo from "@/assets/providers/perplexity.svg"
import perplexity_agentLogo from "@/assets/providers/perplexity-agent.png"
import moonshotaiLogo from "@/assets/providers/moonshotai.svg"
import openaiLogo from "@/assets/providers/openai.svg"
import xpersonaLogo from "@/assets/providers/xpersona.png"
import sarvamLogo from "@/assets/providers/sarvam.png"
import zaiLogo from "@/assets/providers/zai.png"
import inferxLogo from "@/assets/providers/inferx.png"
import meganovaLogo from "@/assets/providers/meganova.png"
import stepfunLogo from "@/assets/providers/stepfun.png"
import cortecsLogo from "@/assets/providers/cortecs.png"
import xiaomi_token_plan_sgpLogo from "@/assets/providers/xiaomi-token-plan-sgp.png"
import hpc_aiLogo from "@/assets/providers/hpc-ai.png"
import minimax_cnLogo from "@/assets/providers/minimax-cn.png"
import ebcloudLogo from "@/assets/providers/ebcloud.png"
import databricksLogo from "@/assets/providers/databricks.svg"
import minimax_cn_coding_planLogo from "@/assets/providers/minimax-cn-coding-plan.png"
import ollamaLogo from "@/assets/providers/ollama.svg"

export const PROVIDER_LOGOS: Record<string, string> = {
  // --- Sentinels (always available) ---
  "ollama": ollamaLogo,
  "ollama-cloud": ollama_cloudLogo,
  openai_compatible: openaiLogo,

  // --- Major labs ---
  "openai": openaiLogo,
  "anthropic": anthropicLogo,
  "google": googleLogo,
  "google-vertex": google_vertexLogo,
  "google-vertex-anthropic": google_vertex_anthropicLogo,
  "xai": xaiLogo,
  "meta": metaLogo,
  "mistral": mistralLogo,
  "deepseek": deepseekLogo,
  "cohere": cohereLogo,
  "groq": groqLogo,
  "amazon-bedrock": amazon_bedrockLogo,
  "azure": azureLogo,
  "azure-cognitive-services": azure_cognitive_servicesLogo,
  "nvidia": nvidiaLogo,

  // --- Local / dev tooling ---
  "lmstudio": lmstudioLogo,
  "opencode": opencodeLogo,
  "opencode-go": opencode_goLogo,

  // --- Cloud inference & gateways ---
  "zhipuai": zhipuaiLogo,
  "anyapi": anyapiLogo,
  "tencent-tokenhub": tencent_tokenhubLogo,
  "fireworks-ai": fireworks_aiLogo,
  "wandb": wandbLogo,
  "crossmodel": crossmodelLogo,
  "claudinio": claudinioLogo,
  "snowflake-cortex": snowflake_cortexLogo,
  "poe": poeLogo,
  "baseten": basetenLogo,
  "nebius": nebiusLogo,
  "vivgrid": vivgridLogo,
  "thinkingmachines": thinkingmachinesLogo,
  "lilac": lilacLogo,
  "zhipuai-coding-plan": zhipuai_coding_planLogo,
  "nano-gpt": nano_gptLogo,
  "fastrouter": fastrouterLogo,
  "nearai": nearaiLogo,
  "daoxe": daoxeLogo,
  "crof": crofLogo,
  "abliteration-ai": abliteration_aiLogo,
  "alibaba-coding-plan-cn": alibaba_coding_plan_cnLogo,
  "llmgateway": llmgatewayLogo,
  "kenari": kenariLogo,
  "friendli": friendliLogo,
  "sakana": sakanaLogo,
  "trustedrouter": trustedrouterLogo,
  "atomic-chat": atomic_chatLogo,
  "inception": inceptionLogo,
  "cloudflare-workers-ai": cloudflare_workers_aiLogo,
  "modelscope": modelscopeLogo,
  "github-copilot": github_copilotLogo,
  "302ai": p302aiLogo,
  "helicone": heliconeLogo,
  "alibaba-coding-plan": alibaba_coding_planLogo,
  "submodel": submodelLogo,
  "neon": neonLogo,
  "ambient": ambientLogo,
  "privatemode-ai": privatemode_aiLogo,
  "unorouter": unorouterLogo,
  "frogbot": frogbotLogo,
  "the-grid-ai": the_grid_aiLogo,
  "sap-ai-core": sap_ai_coreLogo,
  "upstage": upstageLogo,
  "cline-pass": cline_passLogo,
  "regolo-ai": regolo_aiLogo,
  "aiand": aiandLogo,
  "pioneer": pioneerLogo,
  "siliconflow": siliconflowLogo,
  "ai-router": ai_routerLogo,
  "zenmux": zenmuxLogo,
  "inference": inferenceLogo,
  "evroc": evrocLogo,
  "abacus": abacusLogo,
  "empiriolabs": empiriolabsLogo,
  "alibaba-token-plan": alibaba_token_planLogo,
  "wafer.ai": wafer_aiLogo,
  "clarifai": clarifaiLogo,
  "iflowcn": iflowcnLogo,
  "gitlab": gitlabLogo,
  "venice": veniceLogo,
  "scaleway": scalewayLogo,
  "togetherai": togetheraiLogo,
  "digitalocean": digitaloceanLogo,
  "moonshotai-cn": moonshotai_cnLogo,
  "ovhcloud": ovhcloudLogo,
  "zeldoc": zeldocLogo,
  "auriko": aurikoLogo,
  "qihang-ai": qihang_aiLogo,
  "berget": bergetLogo,
  "moark": moarkLogo,
  "nova": novaLogo,
  "vultr": vultrLogo,
  "io-net": io_netLogo,
  "neuralwatt": neuralwattLogo,
  "aki-io": aki_ioLogo,
  "hetzner": hetznerLogo,
  "zenifra": zenifraLogo,
  "aihubmix": aihubmixLogo,
  "morph": morphLogo,
  "umans-ai-coding-plan": umans_ai_coding_planLogo,
  "umans-ai": umans_aiLogo,
  "ofox": ofoxLogo,
  "orcarouter": orcarouterLogo,
  "xiaomi-token-plan-cn": xiaomi_token_plan_cnLogo,
  "v0": v0Logo,
  "poolside": poolsideLogo,
  "routing-run": routing_runLogo,
  "tencent-token-plan": tencent_token_planLogo,
  "synthetic": syntheticLogo,
  "zai-coding-plan": zai_coding_planLogo,
  "gmicloud": gmicloudLogo,
  "freemodel": freemodelLogo,
  "xiaomi-token-plan-ams": xiaomi_token_plan_amsLogo,
  "minimax": minimaxLogo,
  "kimi-for-coding": kimi_for_codingLogo,
  "requesty": requestyLogo,
  "llama": llamaLogo,
  "kilo": kiloLogo,
  "merge-gateway": merge_gatewayLogo,
  "subconscious": subconsciousLogo,
  "tencent-coding-plan": tencent_coding_planLogo,
  "alibaba": alibabaLogo,
  "github-models": github_modelsLogo,
  "vercel": vercelLogo,
  "alibaba-cn": alibaba_cnLogo,
  "novita-ai": novita_aiLogo,
  "openrouter": openrouterLogo,
  "huggingface": huggingfaceLogo,
  "minimax-coding-plan": minimax_coding_planLogo,
  "siliconflow-cn": siliconflow_cnLogo,
  "tinfoil": tinfoilLogo,
  "xiaomi": xiaomiLogo,
  "stackit": stackitLogo,
  "deepinfra": deepinfraLogo,
  "cloudflare-ai-gateway": cloudflare_ai_gatewayLogo,
  "lynkr": lynkrLogo,
  "alibaba-token-plan-cn": alibaba_token_plan_cnLogo,
  "stepfun-ai": stepfun_aiLogo,
  "chutes": chutesLogo,
  "cerebras": cerebrasLogo,
  "qiniu-ai": qiniu_aiLogo,
  "longcat": longcatLogo,
  "jiekou": jiekouLogo,
  "perplexity": perplexityLogo,
  "perplexity-agent": perplexity_agentLogo,
  "moonshotai": moonshotaiLogo,
  "xpersona": xpersonaLogo,
  "sarvam": sarvamLogo,
  "zai": zaiLogo,
  "inferx": inferxLogo,
  "meganova": meganovaLogo,
  "stepfun": stepfunLogo,
  "cortecs": cortecsLogo,
  "xiaomi-token-plan-sgp": xiaomi_token_plan_sgpLogo,
  "hpc-ai": hpc_aiLogo,
  "minimax-cn": minimax_cnLogo,
  "ebcloud": ebcloudLogo,
  "databricks": databricksLogo,
  "minimax-cn-coding-plan": minimax_cn_coding_planLogo,
}
