import json
from typing import AsyncGenerator, List, Dict, Any
from anthropic import AsyncAnthropic
from agent.tools.houses import HousesTool
from agent.tools.split_loot import SplitLootTool

class TibiaAgent:
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.houses_tool = HousesTool()
        self.split_loot_tool = SplitLootTool()
        self.system_prompt = self._create_system_prompt()
        self.max_iterations = 18
        
    def _create_system_prompt(self) -> str:
        return """You are Tibia Agent, an AI assistant specialized in helping players with the MMORPG game Tibia.

Your main expertise:
- Finding houses and guildhalls available for auction in different worlds and towns
- Providing detailed information about Tibia real estate market
- Helping players make informed decisions about house purchases
- Analyzing hunting session loot data and calculating fair profit/loss distribution between party members

HOUSE AUCTIONS:
When users ask about houses for auction, use the get_houses_for_auction tool with the appropriate world and town parameters.
Popular Tibia worlds include: Antica, Bona, Celesta, Dolera, Faluna, Garnera, Gladera, Harmonia, Honbra, Impulsa, Javibra, Kalibra, Lobera, Luminera, Menera, Monza, Nefera, Noctera, Olera, Pacera, Peloria, Premia, Quintera, Refugia, Secura, Solidera, Talera, Tornera, Unitera, Venebra, Vita, Wintera, Yonabra, Zuna, Zunera.
Common towns include: Thais, Carlin, Venore, Ab'Dendriel, Kazordoon, Ankrahmun, Port Hope, Liberty Bay, Svargrond, Yalahar, Gray Beach, Farmine, Rathleton, Issavi, etc.

LOOT SPLITTING:
When users provide hunting session data that contains player names with loot, supplies, balance, damage, and healing information, use the split_loot tool to process it.
After using the split_loot tool, your response should ONLY contain the transfer messages from the tool result, nothing else. No explanations, no calculations, just the transfer instructions.

Example response format for loot splitting:
Luis Sainzz: transfer 367043 to Igres

Be helpful and provide clear information about auction details, but for loot splitting responses, only show the transfer instructions.

IMPORTANT: If you're running out of iterations, provide a summary of what you've found so far and mention any limitations."""
    
    def _get_available_tools(self):
        """Returns list of available tools in Anthropic format"""
        return [
            self.houses_tool.get_function_definition(),
            self.split_loot_tool.get_function_definition()
        ]
    
    async def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any], tool_use_id: str) -> Any:
        """Execute a tool and return the result"""
        if tool_name == "get_houses_for_auction":
            return await self.houses_tool.execute(
                world=tool_input.get("world"), 
                town=tool_input.get("town")
            )
        elif tool_name == "split_loot":
            return await self.split_loot_tool.execute(
                session_data=tool_input.get("session_data")
            )
        else:
            return {"error": f"Unknown tool: {tool_name}", "tool_id": tool_use_id}
    
    # ... rest of the methods remain the same as before
    async def _get_fallback_response(self, messages: List[Dict], user_message: str, max_iterations: int) -> str:
        """Generate a fallback response using the AI when max iterations are reached"""
        try:
            fallback_prompt = f"""The conversation has reached the maximum number of processing iterations ({max_iterations}). 
Based on our conversation history, please provide a helpful response to the user's original request: "{user_message}"
Please:
1. Summarize any information that was gathered during our conversation
2. Explain that we reached the processing limit
3. Provide helpful suggestions for how the user could refine their request
4. Be as helpful as possible with whatever information is available
Keep your response informative and user-friendly."""
            fallback_messages = messages + [{
                "role": "user", 
                "content": fallback_prompt
            }]
            
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=[
                    {
                        "type": "text",
                        "text": self.system_prompt,
                        "cache_control": {"type": "ephemeral"}
                    }
                ],
                messages=fallback_messages,
                extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"}
            )
            
            # Extract text from response
            text_parts = []
            for content_block in response.content:
                if content_block.type == "text":
                    text_parts.append(content_block.text)
            
            return "\n".join(text_parts) if text_parts else None
            
        except Exception:
            # If even the fallback fails, return None to indicate we should use the final fallback
            return None
    
    async def chat(self, user_message: str) -> AsyncGenerator[Dict[str, str], None]:
        """Main chat method that yields structured updates during processing"""
        try:
            yield {"type": "progress", "content": "🤖 Processing your request..."}
            
            # Initialize conversation messages
            messages = [{"role": "user", "content": user_message}]
            
            iteration = 0
            
            while iteration < self.max_iterations:
                iteration += 1
                yield {"type": "progress", "content": f"🔄 Iteration {iteration}/{self.max_iterations}"}
                
                # Check if we're approaching the limit and should warn the model
                approaching_limit = iteration >= self.max_iterations - 2
                current_system_prompt = self.system_prompt
                
                if approaching_limit:
                    current_system_prompt += f"\n\nIMPORTANT: You are approaching the iteration limit ({iteration}/{self.max_iterations}). Please provide a final answer with the information you have gathered so far."
                
                # Make API call
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    system=[
                        {
                            "type": "text",
                            "text": current_system_prompt,
                            "cache_control": {"type": "ephemeral"}  # Cache system prompt
                        }
                    ],
                    messages=messages,
                    tools=self._get_available_tools(),
                    extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"}
                )
                
                # Add assistant response to messages
                assistant_content = []
                
                # Check if there are text responses
                for content_block in response.content:
                    if content_block.type == "text":
                        assistant_content.append({
                            "type": "text",
                            "text": content_block.text
                        })
                    elif content_block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": content_block.id,
                            "name": content_block.name,
                            "input": content_block.input
                        })
                
                messages.append({
                    "role": "assistant",
                    "content": assistant_content
                })
                
                # Check if the model wants to use tools
                tool_uses = [block for block in response.content if block.type == "tool_use"]
                
                if tool_uses:
                    yield {"type": "progress", "content": f"🛠️ Agent wants to use {len(tool_uses)} tool(s)"}
                    
                    # Prepare tool results
                    tool_results = []
                    
                    # Execute all tool calls
                    for tool_use in tool_uses:
                        tool_name = tool_use.name
                        tool_input = tool_use.input
                        tool_use_id = tool_use.id
                        
                        yield {"type": "progress", "content": f"🔧 Executing {tool_name}"}
                        
                        # Execute the tool
                        tool_result = await self._execute_tool(tool_name, tool_input, tool_use_id)
                        
                        # Add to tool results
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps(tool_result)
                        })
                    
                    # Add tool results message
                    messages.append({
                        "role": "user",
                        "content": tool_results
                    })
                    
                    # Continue the loop to let the agent process the tool results
                    yield {"type": "progress", "content": "🤖 Processing tool results..."}
                    continue
                
                # If no tool uses, we have the final response
                else:
                    text_content = []
                    for content_block in response.content:
                        if content_block.type == "text":
                            text_content.append(content_block.text)
                    
                    if text_content:
                        yield {"type": "result", "content": "\n".join(text_content)}
                    else:
                        yield {"type": "result", "content": "I'm here to help you with Tibia house auctions and loot splitting! Just ask me about houses in any world and town, or provide hunting session data for loot distribution."}
                    return
            
            # If we've reached max iterations, try to get a proper response
            yield {"type": "progress", "content": f"⚠️ Reached maximum iterations ({self.max_iterations}). Generating final response..."}
            
            # Try to get a fallback response from the AI
            fallback_response = await self._get_fallback_response(messages, user_message, self.max_iterations)
            
            if fallback_response:
                yield {"type": "result", "content": fallback_response}
            else:
                # If AI-generated fallback fails, provide a minimal response
                yield {"type": "result", "content": f"I apologize, but I reached the maximum number of processing steps ({self.max_iterations}) and couldn't complete your request. Please try asking a more specific question or break down your request into smaller parts."}
            
        except Exception as e:
            yield {"type": "result", "content": f"❌ Error: {str(e)}"}
