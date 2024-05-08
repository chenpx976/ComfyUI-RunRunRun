import base64
import time
from aiohttp import web
import server
import os
import requests
import asyncio
import execution
import uuid
import logging
import urllib.request
import urllib.parse

import aiohttp

# 轮询间隔
COMFY_POLLING_INTERVAL_MS = 500
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


import aiohttp
from urllib.parse import urlencode


def get_image_url(filename, subfolder, folder_type):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url = f"http://{COMFY_HOST}/view?" + urlencode(data)
    return url


async def get_image(filename, subfolder, folder_type):
    url = get_image_url(filename, subfolder, folder_type)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                image_data = await response.read()
                # 将图片数据转换为 Base64 编码
                base64_encoded = base64.b64encode(image_data).decode("utf-8")
                return base64_encoded
            else:
                raise Exception(f"Failed to get image, status code: {response.status}")


@server.PromptServer.instance.routes.post("/comfyui-run/run")
async def comfy_run_run(request):
    host = request.host
    print("[comfy_run_run]", host)
    # 拿到当前请求的 host
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
                await asyncio.sleep(COMFY_POLLING_INTERVAL_MS / 1000)  # 修改这里
                retries += 1
        else:
            return {"error": "Max retries reached while waiting for image generation"}
    except Exception as e:
        return {"error": f"Error waiting for image generation: {str(e)}"}
    node_outputs = history[prompt_id]["outputs"]

    for node_id, node_output in node_outputs.items():
        if "images" in node_output:
            for image in node_output["images"]:
                image_url = get_image_url(
                    image["filename"], image["subfolder"], image["type"]
                )
                # image_url 需要替换 host 为当前请求的 host
                image_url = image_url.replace(COMFY_HOST, host)
                image["image_url"] = image_url

    status = 200
    return web.json_response(node_outputs, status=status)


NODE_CLASS_MAPPINGS = {}
