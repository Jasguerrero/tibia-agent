import re
import logging
from datetime import datetime
from typing import Dict, List, Any, Tuple

logger = logging.getLogger(__name__)

class SplitLootTool:
    def __init__(self):
        self.name = "split_loot"
        self.description = "Parses Tibia hunting session loot data and calculates fair distribution of profits/losses between party members"
    
    def get_function_definition(self) -> Dict[str, Any]:
        """Returns the function definition for Anthropic's tool format"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "session_data": {
                        "type": "string",
                        "description": "The raw session data text containing loot, supplies, damage, and healing information for all party members"
                    }
                },
                "required": ["session_data"]
            }
        }
    
    def _parse_session_data(self, session_data: str) -> Tuple[Dict[str, Dict], str, str]:
        """Parse the session data and extract player information"""
        
        # First try normal line splitting
        lines = session_data.strip().split('\n')
        
        # If we only got 1 line, the data might be space-separated instead (WhatsApp bot case)
        if len(lines) == 1 and len(session_data) > 100:  # Arbitrary length check
            logger.info("DEBUG: Single line detected, attempting to reconstruct lines")
            text = lines[0]
            
            # Replace common patterns that should be on new lines
            patterns = [
                (r'(Session:)', r'\n\1'),
                (r'(Loot Type:)', r'\n\1'),
                (r'(Loot:)', r'\n\1'),
                (r'(Supplies:)', r'\n\1'),
                (r'(Balance:)', r'\n\1'),
                (r'(Damage:)', r'\n\1'),
                (r'(Healing:)', r'\n\1'),
                # Player names - look for name before "loot:" but not if it's the first "Loot:"
                (r'([a-zA-Z][a-zA-Z\s]+[a-zA-Z])\s+loot:', r'\n\1\nLoot:'),
                # Handle "(Leader)" pattern
                (r'\(leader\)\s+loot:', r'(Leader)\nLoot:'),
                # Handle numbers followed by player names
                (r'(\d+)\s+([a-zA-Z][a-zA-Z\s]+)\s+loot:', r'\1\n\2\nLoot:'),
            ]
            
            for pattern, replacement in patterns:
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            
            # Split again and clean up
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            
            logger.info(f"DEBUG: Reconstructed {len(lines)} lines from single line input")
            for i, line in enumerate(lines[:10]):  # Log first 10 lines only
                logger.info(f"DEBUG Line {i}: '{line}'")
        
        # Now proceed with normal parsing
        players = {}
        session_info = ""
        loot_type = ""
        current_player = None
        skip_next_stats = False  # Flag to skip total stats after session info
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Extract session info - these lines contain dates, times, session duration
            if (line.startswith("Session data:") or 
                line.startswith("Session:") or 
                "From 20" in line or  # Date patterns
                re.match(r'\d{2}:\d{2}h', line)):  # Time duration pattern
                session_info += line + "\n"
                skip_next_stats = True  # Skip the next few stat lines as they're totals
                continue
            elif line.startswith("Loot Type:"):
                loot_type = line.split(":", 1)[1].strip()
                session_info += line + "\n"
                continue
            
            # Skip total loot/supplies/balance lines that come after session info
            elif skip_next_stats and line.startswith(("Loot:", "Supplies:", "Balance:")):
                session_info += line + "\n"  # Add to session info since these are totals
                continue
            else:
                skip_next_stats = False
            
            # Check if this line is a stat line
            if any(line.startswith(prefix) for prefix in ["Loot:", "Supplies:", "Balance:", "Damage:", "Healing:"]):
                # This is a stat line, parse it for current player
                if current_player and ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip().replace(",", "")
                    
                    try:
                        # Handle negative values
                        if value.startswith("-"):
                            players[current_player][key] = -int(value[1:])
                        else:
                            players[current_player][key] = int(value)
                    except ValueError:
                        logger.warning(f"Could not parse value '{value}' for key '{key}'")
                        players[current_player][key] = value
            else:
                # This should be a player name line
                if (line and 
                    not line.startswith(("Session", "Loot Type")) and
                    "From 20" not in line and
                    not re.match(r'\d{2}:\d{2}h', line) and
                    not any(line.startswith(prefix) for prefix in ["Loot:", "Supplies:", "Balance:", "Damage:", "Healing:"])):
                    
                    # Clean up player name (remove leader designation)
                    player_name = line.replace("(Leader)", "").strip()
                    if player_name:  # Make sure it's not empty
                        current_player = player_name
                        players[current_player] = {}
                        logger.info(f"DEBUG: Found player: '{current_player}'")
        
        logger.info(f"DEBUG: Final players parsed: {list(players.keys())}")
        return players, session_info, loot_type
    
    def _calculate_split(self, players: Dict[str, Dict]) -> List[str]:
        """Calculate how much each player should pay or receive and return transfer messages"""
        
        # Calculate total loot and supplies
        total_loot = sum(player_data.get('loot', 0) for player_data in players.values())
        total_supplies = sum(player_data.get('supplies', 0) for player_data in players.values())
        
        # Net profit/loss
        net_profit = total_loot - total_supplies
        
        # Number of players
        num_players = len(players)
        
        if num_players == 0:
            return []
        
        # Each player's fair share
        fair_share = net_profit / num_players
        
        # Calculate what each player should receive/pay
        player_balances = {}
        for player_name, player_data in players.items():
            current_balance = player_data.get('balance', 0)
            difference = fair_share - current_balance
            player_balances[player_name] = {
                'current_balance': current_balance,
                'fair_share': fair_share,
                'needs_to_receive': difference if difference > 0 else 0,
                'needs_to_pay': -difference if difference < 0 else 0
            }
        
        # Generate transfer instructions
        transfers = []
        
        # Get players who need to pay and receive
        payers = [(name, data['needs_to_pay']) for name, data in player_balances.items() if data['needs_to_pay'] > 0]
        receivers = [(name, data['needs_to_receive']) for name, data in player_balances.items() if data['needs_to_receive'] > 0]
        
        # Sort by amount (largest first)
        payers.sort(key=lambda x: x[1], reverse=True)
        receivers.sort(key=lambda x: x[1], reverse=True)
        
        # Create transfers
        payer_idx = 0
        receiver_idx = 0
        
        while payer_idx < len(payers) and receiver_idx < len(receivers):
            payer_name, payer_amount = payers[payer_idx]
            receiver_name, receiver_amount = receivers[receiver_idx]
            
            # Transfer the minimum of what payer owes and receiver needs
            transfer_amount = min(payer_amount, receiver_amount)
            
            if transfer_amount > 0:
                transfers.append(f"{payer_name}: transfer {int(transfer_amount)} to {receiver_name}")
                
                # Update remaining amounts
                payers[payer_idx] = (payer_name, payer_amount - transfer_amount)
                receivers[receiver_idx] = (receiver_name, receiver_amount - transfer_amount)
            
            # Move to next payer/receiver if current one is settled
            if payers[payer_idx][1] <= 0:
                payer_idx += 1
            if receivers[receiver_idx][1] <= 0:
                receiver_idx += 1
        
        return transfers
    
    def _extract_damage_healing(self, players: Dict[str, Dict]) -> List[Dict[str, Any]]:
        """Extract damage and healing data for each player"""
        damage_healing_data = []
        
        for player_name, player_data in players.items():
            player_stats = {
                "player": player_name,
                "damage": player_data.get('damage', 0),
                "healing": player_data.get('healing', 0)
            }
            damage_healing_data.append(player_stats)
        
        return damage_healing_data
    
    async def execute(self, session_data: str, db = None) -> Dict[str, Any]:
        """Execute the split loot calculation"""
        result = {}
        try:
            logger.info(f"DEBUG: Received session_data length: {len(session_data)}")
            logger.info(f"DEBUG: First 200 chars: '{session_data[:200]}...'")
            
            # Parse the session data
            players, session_info, loot_type = self._parse_session_data(session_data)
            
            if not players:
                return {
                    "success": False,
                    "error": "No player data found in the session data",
                    "transfers": []
                }
            
            # Calculate the split
            transfers = self._calculate_split(players)
            
            # Extract damage and healing data
            damage_healing_data = self._extract_damage_healing(players)
            
            # Calculate totals for summary
            total_loot = sum(player_data.get('loot', 0) for player_data in players.values())
            total_supplies = sum(player_data.get('supplies', 0) for player_data in players.values())
            net_profit = total_loot - total_supplies
            result = {
                "success": True,
                "transfers": transfers,
                "damage_healing_data": damage_healing_data,
                "session_summary": {
                    "total_loot": total_loot,
                    "total_supplies": total_supplies,
                    "net_profit": net_profit,
                    "loot_type": loot_type,
                    "session_info": session_info.strip()
                },
                "players_parsed": list(players.keys())  # For debugging
            }
            
        except Exception as e:
            logger.error(f"Exception in execute: {str(e)}", exc_info=True)
            result = {
                "success": False,
                "error": f"Failed to process loot split: {str(e)}",
                "message": session_data,
                "transfers": []
            }
        finally:
            logger.info(f"Inserting: {result}")
            await self._insert_data(result.copy(), db)
            return result
        
    async def _insert_data(self, data, db):
        data["created_at"] = datetime.now()
        if db is None:
            logger.info("Skipping insertion")
            return
        collection = db["session_data"]
        result = await collection.insert_one(data)
            
        logger.info(f"Stored loot session in database with ID: {str(result.inserted_id)}")
