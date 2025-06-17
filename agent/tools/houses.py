import aiohttp
import json
import ssl
import asyncio
from typing import Dict, Any, Union
import logging

logger = logging.getLogger(__name__)

class HousesTool:
    def __init__(self):
        self.base_url = "https://api.tibiadata.com/v4/houses"
    
    def get_function_definition(self) -> Dict[str, Any]:
        """Returns the function definition for Anthropic function calling"""
        return {
            "name": "get_houses_for_auction",
            "description": "Get houses available for auction in a specific world and town in Tibia",
            "input_schema": {
                "type": "object",
                "properties": {
                    "world": {
                        "type": "string",
                        "description": "The Tibia world name (e.g., 'Antica', 'Bona', 'Celesta')"
                    },
                    "town": {
                        "type": "string", 
                        "description": "The town name (e.g., 'Thais', 'Carlin', 'Venore', 'Ab\'Dendriel')"
                    }
                },
                "required": ["world", "town"]
            }
        }
    
    async def execute(self, world: str, town: str) -> Union[Dict[str, Any], str]:
        """Execute the houses tool and return result or error"""
        try:
            url = f"{self.base_url}/{world}/{town}"
            
            # Create SSL context to handle certificate issues
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            # Create connector with SSL context and timeout
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            timeout = aiohttp.ClientTimeout(total=10)
            
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                logger.info(f"Fetching: {url}")
                async with session.get(url) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            # Check if there's an error in the response
            if data.get("information", {}).get("status", {}).get("error", 0) != 0:
                error_msg = data.get("information", {}).get("status", {}).get("message", "Unknown error")
                return {"sucess": "false", "error_message": f"API Error: {error_msg}"}
            
            houses_data = data.get("houses", {})
            house_list = houses_data.get("house_list", [])
            guildhall_list = houses_data.get("guildhall_list", [])
            
            # Filter only auctioned houses
            auctioned_houses = [house for house in house_list if house.get("auctioned", False)]
            auctioned_guildhalls = [gh for gh in guildhall_list if gh.get("auctioned", False)]
            
            result = {
                "world": world,
                "town": town,
                "auctioned_houses": auctioned_houses,
                "auctioned_guildhalls": auctioned_guildhalls,
                "total_auctions": len(auctioned_houses) + len(auctioned_guildhalls),
                "success": True
            }
            
            return result
            
        except aiohttp.ClientError as e:
            logger.error(f"Client error: {str(e)}")
            return f"Error fetching data from Tibia API: {str(e)}"
        except asyncio.TimeoutError:
            logger.error("Request timeout")
            return f"Timeout error: API request took too long"
        except KeyError as e:
            logger.error(f"Key error: {str(e)}")
            return f"Error parsing API response: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return f"Unexpected error: {str(e)}"
