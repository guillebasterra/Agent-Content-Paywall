"""Uses the existing writer API. Does not implement or alter payments."""
import httpx
from app.discord_import import ImportFailure

async def publish_snapshot(api_url, writer_token, payload, price_usd):
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
        result = await http.post(api_url + '/articles', headers={'Authorization': 'Bearer ' + writer_token},
            data={'title': payload['title'], 'abstract': payload['summary'], 'price_usd': price_usd,
                  'keywords': 'discord,community,snapshot', 'preview_mode': 'none', 'license': 'ai-input'},
            files={'file': ('snapshot.md', payload['body'].encode(), 'text/markdown')})
    if result.status_code != 201:
        raise ImportFailure('Publication did not return success. Check the catalog before any manual retry.')
    return result.json()['id']
