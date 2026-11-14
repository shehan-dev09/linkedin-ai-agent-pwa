import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN_CONFIG_PATH = ".linkedin_token.json"


def get_configured_token() -> str:
    """
    Retrieves the LinkedIn Access Token from either the local runtime config
    (saved via Studio UI) or the .env file.
    """
    if os.path.exists(TOKEN_CONFIG_PATH):
        try:
            with open(TOKEN_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                token = data.get("access_token", "").strip()
                if token:
                    return token
        except Exception:
            pass

    load_dotenv(override=True)
    return os.getenv("LINKEDIN_ACCESS_TOKEN", "").strip()


def save_configured_token(access_token: str) -> None:
    """Saves the LinkedIn Access Token to a private, non-public root config file."""
    with open(TOKEN_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"access_token": access_token.strip()}, f, indent=2)


def verify_linkedin_connection(access_token: str | None = None) -> dict:
    """
    Verifies the LinkedIn OAuth2 token against LinkedIn's /v2/userinfo or /v2/me
    endpoints and returns the resolved Member URN and profile name.
    """
    token = (access_token if access_token is not None else get_configured_token()).strip()
    if not token:
        return {
            "connected": False,
            "mode": "sandbox",
            "member_urn": None,
            "profile_name": None,
            "message": "No LinkedIn Access Token configured. Running in Sandbox Simulation Mode."
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    # 1. Try OpenID Connect /v2/userinfo endpoint (standard for modern LinkedIn apps)
    try:
        resp = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            sub = data.get("sub")
            name = data.get("name") or f"{data.get('given_name', '')} {data.get('family_name', '')}".strip()
            if sub:
                return {
                    "connected": True,
                    "mode": "live",
                    "member_urn": f"urn:li:person:{sub}",
                    "profile_name": name or "Verified LinkedIn Member",
                    "message": "LinkedIn Live API connected via OpenID Connect."
                }
    except Exception as e:
        print(f"Warning: /v2/userinfo check failed: {e}")

    # 2. Fallback to legacy /v2/me endpoint
    try:
        resp = requests.get("https://api.linkedin.com/v2/me", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            member_id = data.get("id")
            first_name = data.get("localizedFirstName", "")
            last_name = data.get("localizedLastName", "")
            full_name = f"{first_name} {last_name}".strip()
            if member_id:
                return {
                    "connected": True,
                    "mode": "live",
                    "member_urn": f"urn:li:person:{member_id}",
                    "profile_name": full_name or "Verified LinkedIn Member",
                    "message": "LinkedIn Live API connected via v2/me."
                }
        elif resp.status_code == 401:
            return {
                "connected": False,
                "mode": "sandbox",
                "member_urn": None,
                "profile_name": None,
                "message": "Invalid or expired LinkedIn Access Token (HTTP 401)."
            }
    except Exception as e:
        return {
            "connected": False,
            "mode": "sandbox",
            "member_urn": None,
            "profile_name": None,
            "message": f"Network error verifying token: {str(e)}"
        }

    return {
        "connected": False,
        "mode": "sandbox",
        "member_urn": None,
        "profile_name": None,
        "message": "Could not resolve LinkedIn Member URN. Ensure 'openid', 'profile', and 'w_member_social' scopes are enabled."
    }


def publish_to_linkedin(post_text: str, image_path: str | None = None) -> dict:
    """
    Publishes a post (with an optional 1080x1080 image card) to LinkedIn using the
    official LinkedIn UGC Posts API. Falls back to Sandbox Mode if no token is set.
    """
    token = get_configured_token()
    person_urn = os.getenv("LINKEDIN_PERSON_URN", "").strip()

    if not token:
        print("Notice: LINKEDIN_ACCESS_TOKEN not found. Executing in Sandbox Simulation Mode.")
        return {
            "mode": "simulated",
            "post_urn": "urn:li:share:simulated_local_test",
            "post_url": "https://www.linkedin.com/in/shehan-nadeesha/",
            "message": "Published in Sandbox Mode (Add LINKEDIN_ACCESS_TOKEN in Settings for live publishing)."
        }

    # Resolve Person URN dynamically if not explicitly set
    if not person_urn:
        verification = verify_linkedin_connection(token)
        if not verification.get("connected") or not verification.get("member_urn"):
            raise RuntimeError(verification.get("message", "Failed to verify LinkedIn token."))
        person_urn = verification["member_urn"]

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json"
    }

    asset_urn = None

    # Step 1: Register and upload binary image if local file exists
    if image_path and os.path.exists(image_path):
        print(f"Registering image upload with LinkedIn API for: {image_path}")
        register_url = "https://api.linkedin.com/v2/assets?action=registerUpload"
        register_payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": person_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent"
                    }
                ]
            }
        }

        reg_resp = requests.post(register_url, headers=headers, json=register_payload, timeout=20)
        if reg_resp.status_code not in (200, 201):
            raise RuntimeError(f"LinkedIn image registration failed ({reg_resp.status_code}): {reg_resp.text}")

        reg_data = reg_resp.json()
        upload_url = (
            reg_data["value"]["uploadMechanism"]
            ["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        )
        asset_urn = reg_data["value"]["asset"]

        print("Uploading 1080x1080 Liquid Glass visual to LinkedIn media servers...")
        with open(image_path, "rb") as img_file:
            upload_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream"
            }
            up_resp = requests.put(upload_url, headers=upload_headers, data=img_file, timeout=45)
            if up_resp.status_code not in (200, 201):
                raise RuntimeError(f"LinkedIn binary image upload failed ({up_resp.status_code}): {up_resp.text}")

    # Step 2: Create the UGC Post on LinkedIn
    print("Publishing UGC post to LinkedIn feed...")
    post_url = "https://api.linkedin.com/v2/ugcPosts"

    if asset_urn:
        share_content = {
            "shareCommentary": {"text": post_text},
            "shareMediaCategory": "IMAGE",
            "media": [
                {
                    "status": "READY",
                    "description": {"text": "AI/ML Engineering Briefing"},
                    "media": asset_urn,
                    "title": {"text": "AI/ML Engineering Insights"}
                }
            ]
        }
    else:
        share_content = {
            "shareCommentary": {"text": post_text},
            "shareMediaCategory": "NONE"
        }

    post_payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": share_content
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    post_resp = requests.post(post_url, headers=headers, json=post_payload, timeout=20)
    if post_resp.status_code not in (200, 201):
        raise RuntimeError(f"LinkedIn post creation failed ({post_resp.status_code}): {post_resp.text}")

    post_urn = post_resp.json().get("id", "urn:li:ugcPost:published")
    feed_url = f"https://www.linkedin.com/feed/update/{post_urn}/"
    print(f"Successfully published to LinkedIn! Post URN: {post_urn}")

    return {
        "mode": "live",
        "post_urn": post_urn,
        "post_url": feed_url,
        "message": "Successfully published live to your LinkedIn profile!"
    }