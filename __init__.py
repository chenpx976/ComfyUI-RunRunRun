import time
from aiohttp import web
import server
import os
import requests
import execution
import uuid
import logging

# 轮询间隔
COMFY_POLLING_INTERVAL_MS = 250
# Maximum number of poll attempts
COMFY_POLLING_MAX_RETRIES = 1000
# Host where ComfyUI is running
COMFY_HOST = "127.0.0.1:8188"


async def post_prompt(request):
    prompt_server = server.PromptServer.instance
    json_data = await request.json()
    json_data = prompt_server.trigger_on_prompt(json_data)
    print("[comfy_run_run]:data", json_data)

    if "number" in json_data:
        number = float(json_data["number"])
    else:
        number = prompt_server.number
        if "front" in json_data:
            if json_data["front"]:
                number = -number

        prompt_server.number += 1

    if "prompt" in json_data:
        prompt = json_data["prompt"]
        valid = execution.validate_prompt(prompt)
        extra_data = {}
        if "extra_data" in json_data:
            extra_data = json_data["extra_data"]

        if "client_id" in json_data:
            extra_data["client_id"] = json_data["client_id"]
        if valid[0]:
            prompt_id = str(uuid.uuid4())
            outputs_to_execute = valid[2]
            prompt_server.prompt_queue.put(
                (number, prompt_id, prompt, extra_data, outputs_to_execute)
            )
            response = {
                "prompt_id": prompt_id,
                "number": number,
                "node_errors": valid[3],
            }
            return response
        else:
            logging.warning("invalid prompt: {}".format(valid[1]))
            return {"error": valid[1], "node_errors": valid[3]}

    else:
        return {"error": "no prompt", "node_errors": []}


async def get_history(prompt_id):
    prompt_server = server.PromptServer.instance
    return prompt_server.prompt_queue.get_history(prompt_id=prompt_id)


@server.PromptServer.instance.routes.post("/comfyui-run/run")
async def comfy_run_run(request):
    print("[comfy_run_run]")
    prompt_response = await post_prompt(request)
    print("[comfy_run_run]:response", prompt_response)
    prompt_id = prompt_response.get("prompt_id")
    print("[comfy_run_run]:prompt_id", prompt_id)

    retries = 0
    status = ""
    try:
        print("getting request")
        while retries < COMFY_POLLING_MAX_RETRIES:
            history = await get_history(prompt_id)
            print("[comfy_run_run]:history", history)
            # Exit the loop if we have found the history
            if prompt_id in history and history[prompt_id].get("outputs"):
                break
            else:
                # Wait before trying again
                time.sleep(COMFY_POLLING_INTERVAL_MS / 1000)
                retries += 1
        else:
            return {"error": "Max retries reached while waiting for image generation"}
    except Exception as e:
        return {"error": f"Error waiting for image generation: {str(e)}"}

    status = 200
    # res = {"error": "no prompt", "node_errors": [], "json_data": json_data}
    return web.json_response(history, status=status)


NODE_CLASS_MAPPINGS = {}
