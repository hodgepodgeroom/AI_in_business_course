import { env } from "cloudflare:workers";
import { getChatGPTUser } from "../../chatgpt-auth";
import { handleApi } from "../../../lib/api";
export const dynamic = "force-dynamic";
export const GET = (req: Request) => handleApi(req, env, getChatGPTUser);
export const POST = GET;
