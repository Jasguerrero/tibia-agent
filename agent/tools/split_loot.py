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
        
        # Handle single line format (WhatsApp case)
        text = session_data.strip().lower()
        original_text = session_data.strip()
        
        logger.info(f"DEBUG: Parsing text: {original_text}")
        
        players = {}
        session_info = ""
        loot_type = ""
        
        # Extract session info using regex
        date_match = re.search(r'from \d{4}-\d{2}-\d{2}, \d{2}:\d{2}:\d{2} to \d{4}-\d{2}-\d{2}, \d{2}:\d{2}:\d{2}', original_text, re.IGNORECASE)
        if date_match:
            session_info += date_match.group() + "\n"
        
        session_match = re.search(r'session:\s*\d{2}:\d{2}h', original_text, re.IGNORECASE)
        if session_match:
            session_info += session_match.group() + "\n"
        
        loot_type_match = re.search(r'loot type:\s*(\w+)', original_text, re.IGNORECASE)
        if loot_type_match:
            loot_type = loot_type_match.group(1)
            session_info += f"Loot Type: {loot_type}\n"
        
        # Extract session totals (first occurrence of loot/supplies/balance)
        session_loot_match = re.search(r'loot:\s*([\d,]+)', original_text, re.IGNORECASE)
        if session_loot_match:
            session_info += f"Loot: {session_loot_match.group(1)}\n"
        
        session_supplies_match = re.search(r'supplies:\s*([\d,]+)', original_text, re.IGNORECASE)
        if session_supplies_match:
            session_info += f"Supplies: {session_supplies_match.group(1)}\n"
        
        session_balance_match = re.search(r'balance:\s*([-\d,]+)', original_text, re.IGNORECASE)
        if session_balance_match:
            session_info += f"Balance: {session_balance_match.group(1)}\n"
        
        # Now extract players and their stats
        # Pattern to find player sections: player_name followed by stats
        
        # First, let's find all player names
        # Look for patterns like "igres loot:" and "luis sainzz (leader) loot:"
        player_patterns = []
        
        # Find potential player names by looking for text before "loot:" that's not at the beginning
        # Skip the first "loot:" as that's the session total
        loot_positions = []
        for match in re.finditer(r'loot:\s*[\d,]+', original_text, re.IGNORECASE):
            loot_positions.append(match.start())
        
        logger.info(f"DEBUG: Found {len(loot_positions)} loot positions: {loot_positions}")
        
        # Skip the first loot (session total), process the rest as player data
        for i, loot_pos in enumerate(loot_positions[1:], 1):  # Skip first one
            # Look backwards from this loot position to find the player name
            # Find the previous stat end or beginning of string
            search_start = 0
            if i > 1:  # If not the first player
                # Find the end of previous player's stats
                prev_section = original_text[:loot_pos]
                # Look for the last healing/damage/balance before this loot
                last_stat_match = None
                for stat_pattern in [r'healing:\s*[\d,]+', r'damage:\s*[\d,]+', r'balance:\s*[-\d,]+']:
                    for match in re.finditer(stat_pattern, prev_section, re.IGNORECASE):
                        if not last_stat_match or match.end() > last_stat_match.end():
                            last_stat_match = match
                if last_stat_match:
                    search_start = last_stat_match.end()
            else:
                # For first player, start after session balance
                if session_balance_match:
                    search_start = session_balance_match.end()
            
            # Extract potential player name
            player_section = original_text[search_start:loot_pos].strip()
            logger.info(f"DEBUG: Player section {i}: '{player_section}'")
            
            # Clean up the player name (remove trailing spaces and common words)
            player_name = player_section.replace("(leader)", "").replace("(Leader)", "").strip()
            if player_name:
                logger.info(f"DEBUG: Found player: '{player_name}'")
                players[player_name] = {}
                
                # Now extract this player's stats
                # Find the end of this player's section
                if i < len(loot_positions) - 1:  # Not the last player
                    next_loot_pos = loot_positions[i + 1]
                    # Find the player name before the next loot
                    player_section_end = next_loot_pos
                    # Look backwards from next loot to find where this player's stats end
                    section_before_next = original_text[loot_pos:next_loot_pos]
                    # Find the last stat in this section
                    last_stat_end = loot_pos
                    for stat_pattern in [r'healing:\s*[\d,]+', r'damage:\s*[-\d,]+', r'balance:\s*[-\d,]+', r'supplies:\s*[\d,]+']:
                        for match in re.finditer(stat_pattern, section_before_next, re.IGNORECASE):
                            actual_pos = loot_pos + match.end()
                            if actual_pos > last_stat_end:
                                last_stat_end = actual_pos
                    player_section_end = last_stat_end
                else:  # Last player
                    player_section_end = len(original_text)
                
                # Extract stats for this player
                player_stats_text = original_text[loot_pos:player_section_end]
                logger.info(f"DEBUG: Player '{player_name}' stats section: '{player_stats_text}'")
                
                # Extract individual stats
                for stat_name, pattern in [
                    ('loot', r'loot:\s*([\d,]+)'),
                    ('supplies', r'supplies:\s*([\d,]+)'),
                    ('balance', r'balance:\s*([-\d,]+)'),
                    ('damage', r'damage:\s*([\d,]+)'),
                    ('healing', r'healing:\s*([\d,]+)')
                ]:
                    match = re.search(pattern, player_stats_text, re.IGNORECASE)
                    if match:
                        value_str = match.group(1).replace(',', '')
                        try:
                            if value_str.startswith('-'):
                                players[player_name][stat_name] = -int(value_str[1:])
                            else:
                                players[player_name][stat_name] = int(value_str)
                            logger.info(f"DEBUG: Set {player_name}[{stat_name}] = {players[player_name][stat_name]}")
                        except ValueError:
                            logger.warning(f"Could not parse {stat_name} value: {value_str}")
        
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
