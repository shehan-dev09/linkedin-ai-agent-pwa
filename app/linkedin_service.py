import os
from dotenv import load_dotenv
import requests

load_dotenv()


def publish_to_linkedin(post_text: str, image_path: str) -> dict:
    """Publishes the approved post and image to LinkedIn using the Official LinkedIn API.

    Requires LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN in the .env file.
    """
    access_token = os.getenv("LINKEDIN_ACCESS_TOKEN")
    person_urn = os.getenv(
        "LINKEDIN_PERSON_URN"
    )  # Format: urn:li:person:XXXXXX

    # If LinkedIn credentials are not configured yet, return a helpful status
    if not access_token or not person_urn:
        return {
            "status": "simulated",
            "message": "Post approved! (Add LINKEDIN_ACCESS_TOKEN in .env to enable live auto-publishing).",
        }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    try:
        # Step 1: Register the image upload with LinkedIn
        register_url = "https://api.linkedin.com/v2/assets?action=registerUpload"
        register_payload = {
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
            register_url, headers=headers, json=register_payload, timeout=15
        )
        reg_res.raise_for_status()
        reg_data = reg_res.json()

        upload_url = reg_data["value"]["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = reg_data["value"]["asset"]

        # Step 2: Upload the binary image file
        with open(image_path, "rb") as img_file:
            upload_headers = {"Authorization": f"Bearer {access_token}"}
            up_res = requests.put(
                upload_url, headers=upload_headers, data=img_file, timeout=30
            )
            up_res.raise_for_status()

        # Step 3: Create the LinkedIn UGC Post with the uploaded image
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
                            "description": {"text": "AI & ML Engineering Insight"},
                            "media": asset_urn,
                            "title": {"text": "Shehan Nadeesha | AI/ML Engineer"},
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
        return {"status": "error", "message": f"LinkedIn API Error: {str(e)}"}