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
        lines = session_data.strip().split('\n')
        players = {}
        session_info = ""
        loot_type = ""
        
        current_player = None
        parsing_session_totals = False  # Flag to track if we're in the session totals section
        
        for i, line in enumerate(lines):
            line = line.strip()
            logger.info(f"DEBUG Processing line {i}: '{line}'")
            
            # 1. Check for session header info
            if (line.startswith("Session data:") or 
                "from 20" in line.lower() or  # Date line
                line.startswith("Session:") or 
                re.match(r'\d{2}:\d{2}h', line)):  # Duration
                logger.info(f"  -> SESSION HEADER")
                session_info += line + "\n"
                parsing_session_totals = True  # Next stats will be session totals
                continue
                
            # 2. Check for loot type
            elif line.startswith("Loot Type:"):
                logger.info(f"  -> LOOT TYPE")
                loot_type = line.split(":", 1)[1].strip()
                session_info += line + "\n"
                continue
            
            # 3. Check if this is a stat line (has colon and looks like stat)
            elif ":" in line and any(line.lower().startswith(prefix.lower()) for prefix in ["Loot:", "Supplies:", "Balance:", "Damage:", "Healing:"]):
                logger.info(f"  -> STAT LINE")
                
                # If we're parsing session totals, add to session info and skip
                if parsing_session_totals:
                    logger.info(f"    -> Adding to session totals")
                    session_info += line + "\n"
                    continue
                
                # Otherwise, this is a player stat
                if current_player:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip().replace(",", "")
                    
                    try:
                        if value.startswith("-"):
                            players[current_player][key] = -int(value[1:])
                        else:
                            players[current_player][key] = int(value)
                        logger.info(f"    -> Set {current_player}[{key}] = {players[current_player][key]}")
                    except ValueError:
                        logger.warning(f"Could not parse value '{value}' for key '{key}'")
                        players[current_player][key] = value
                else:
                    logger.warning(f"    -> Found stat line but no current player!")
            
            # 4. This should be a player name
            else:
                # Skip empty lines
                if not line:
                    continue
                    
                logger.info(f"  -> PLAYER NAME: '{line}'")
                parsing_session_totals = False  # We're past session totals now
                
                # Clean up player name (remove leader designation)
                player_name = line.replace("(Leader)", "").replace("(leader)", "").strip()
                if player_name:
                    current_player = player_name
                    players[current_player] = {}
                    logger.info(f"    -> Added player: '{current_player}'")
        
        logger.info(f"DEBUG: Final players parsed: {list(players.keys())}")
        logger.info(f"DEBUG: Session info: {session_info}")
        logger.info(f"DEBUG: Loot type: {loot_type}")
        
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
