"""LinkedIn Official API Publishing Service with Auto-URN Discovery."""

import os
from typing import Dict
from dotenv import load_dotenv
import requests

load_dotenv()


def _resolve_person_urn(access_token: str) -> str:
    """Automatically fetches the authenticated member's LinkedIn Person URN

    using OpenID Connect (/v2/userinfo) or (/v2/me) so manual URN lookup is not
    required.
    """
    env_urn = os.getenv("LINKEDIN_PERSON_URN")
    if env_urn and env_urn.startswith("urn:li:person:"):
        return env_urn

    headers = {"Authorization": f"Bearer {access_token}"}

    # 1. Try OpenID Connect userinfo endpoint (Standard for new LinkedIn Apps)
    res = requests.get(
        "https://api.linkedin.com/v2/userinfo", headers=headers, timeout=10
    )
    if res.status_code == 200:
        sub = res.json().get("sub")
        if sub:
            return f"urn:li:person:{sub}"

    # 2. Fallback to legacy /v2/me endpoint
    res_me = requests.get(
        "https://api.linkedin.com/v2/me", headers=headers, timeout=10
    )
    if res_me.status_code == 200:
        member_id = res_me.json().get("id")
        if member_id:
            return f"urn:li:person:{member_id}"

    raise RuntimeError(
        "Could not resolve LinkedIn Person URN. Check your LINKEDIN_ACCESS_TOKEN permissions."
    )


def publish_to_linkedin(post_text: str, image_path: str) -> Dict[str, str]:
    """Publishes the approved post and generated 1080x1080 visual to LinkedIn.

    Runs in safe simulation mode if LINKEDIN_ACCESS_TOKEN is not set in .env.
    """
    load_dotenv(override=True)
    access_token = os.getenv("LINKEDIN_ACCESS_TOKEN")

    if not access_token:
        return {
            "status": "simulated",
            "message": "Approved! (Simulation Mode: Add LINKEDIN_ACCESS_TOKEN to .env for live LinkedIn publishing).",
        }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    try:
        # Step 1: Automatically resolve Shehan's LinkedIn Person URN
        person_urn = _resolve_person_urn(access_token)

        # Step 2: Register image upload with LinkedIn Assets API
        reg_url = "https://api.linkedin.com/v2/assets?action=registerUpload"
        reg_payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": person_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        reg_res = requests.post(
            reg_url, headers=headers, json=reg_payload, timeout=15
        )
        reg_res.raise_for_status()
        reg_data = reg_res.json()

        upload_url = reg_data["value"]["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = reg_data["value"]["asset"]

        # Step 3: Upload binary image file
        with open(image_path, "rb") as img_file:
            up_res = requests.put(
                upload_url,
                headers={"Authorization": f"Bearer {access_token}"},
                data=img_file,
                timeout=30,
            )
            up_res.raise_for_status()

        # Step 4: Publish UGC Post with image asset
        post_url = "https://api.linkedin.com/v2/ugcPosts"
        post_payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": post_text},
                    "shareMediaCategory": "IMAGE",
                    "media": [
                        {
                            "status": "READY",
                            "description": {
                                "text": "AI & ML Engineering Insight"
                            },
                            "media": asset_urn,
                            "title": {
                                "text": "Shehan Nadeesha | AI/ML Engineer"
                            },
                        }
                    ],
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }
        post_res = requests.post(
            post_url, headers=headers, json=post_payload, timeout=15
        )
        post_res.raise_for_status()

        return {
            "status": "published",
            "message": "Successfully published live to your LinkedIn profile!",
        }

    except Exception as e:
        raise RuntimeError(f"LinkedIn API Error: {str(e)}")