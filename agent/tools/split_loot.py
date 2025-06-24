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
        if len(lines) == 1 and len(session_data) > 100:
            logger.info("DEBUG: Single line detected, attempting to reconstruct lines")
            text = lines[0].lower()  # Work with lowercase for pattern matching
            original_text = lines[0]  # Keep original for final result
            
            # More precise patterns to reconstruct the session data
            # We need to be very careful about the order and specificity
            patterns = [
                # First handle the session header parts
                (r'(session:)', r'\n\1'),
                (r'(loot type:)', r'\n\1'),
                
                # Then handle stat lines - but be more specific
                (r'(?<!loot type: )(?<!session: )(loot:)', r'\n\1'),  # Don't match "loot type:"
                (r'(supplies:)', r'\n\1'),
                (r'(balance:)', r'\n\1'),
                (r'(damage:)', r'\n\1'),
                (r'(healing:)', r'\n\1'),
                
                # Handle player names - look for names followed by loot/supplies/balance/damage/healing
                # But exclude session info patterns
                (r'([a-z\s]+)\s+(loot:|supplies:|balance:|damage:|healing:)', r'\n\1\n\2'),
                
                # Handle (leader) pattern specifically
                (r'\(leader\)\s+(loot:|supplies:|balance:|damage:|healing:)', r'(Leader)\n\1'),
            ]
            
            # Apply patterns to lowercase text but track positions
            working_text = original_text
            for pattern, replacement in patterns:
                working_text = re.sub(pattern, replacement, working_text, flags=re.IGNORECASE)
            
            # Split and clean up
            lines = [line.strip() for line in working_text.split('\n') if line.strip()]
            
            logger.info(f"DEBUG: Reconstructed {len(lines)} lines from single line input")
            for i, line in enumerate(lines):
                logger.info(f"DEBUG Line {i}: '{line}'")
        
        # Now proceed with parsing - with much stricter logic
        players = {}
        session_info = ""
        loot_type = ""
        current_player = None
        in_session_header = True  # Start assuming we're in session header
        
        for i, line in enumerate(lines):
            line = line.strip()
            logger.info(f"DEBUG Processing line {i}: '{line}'")
            
            # Session info detection - be very specific
            if (line.startswith("Session data:") or 
                line.startswith("Session:") or 
                "from 20" in line.lower() or  # Date patterns
                re.match(r'\d{2}:\d{2}h', line) or  # Time duration pattern
                line.startswith("Loot Type:")):
                
                logger.info(f"  -> SESSION INFO")
                session_info += line + "\n"
                if line.startswith("Loot Type:"):
                    loot_type = line.split(":", 1)[1].strip()
                in_session_header = True
                continue
            
            # Skip session totals (the first loot/supplies/balance after session info)
            elif in_session_header and line.startswith(("Loot:", "Supplies:", "Balance:")):
                logger.info(f"  -> SESSION TOTAL (skipping)")
                session_info += line + "\n"
                # Don't set in_session_header = False yet, wait for actual player
                continue
            
            # Check if this is a stat line for current player
            elif any(line.startswith(prefix) for prefix in ["Loot:", "Supplies:", "Balance:", "Damage:", "Healing:"]):
                logger.info(f"  -> STAT LINE for player '{current_player}'")
                in_session_header = False  # We're definitely past session header now
                
                if current_player and ":" in line:
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
            
            # This should be a player name
            else:
                # Very strict player name detection
                # Must not be a session line, must not be a stat line, must not be empty
                # Must not contain common session keywords
                session_keywords = ['session', 'loot type', 'from 20', 'leader' if line == 'leader' else None]
                session_keywords = [k for k in session_keywords if k]  # Remove None
                
                is_session_line = any(keyword in line.lower() for keyword in session_keywords if keyword)
                is_stat_line = any(line.startswith(prefix) for prefix in ["Loot:", "Supplies:", "Balance:", "Damage:", "Healing:"])
                is_time_pattern = re.match(r'\d{2}:\d{2}h', line)
                
                if (line and 
                    not is_session_line and 
                    not is_stat_line and 
                    not is_time_pattern and
                    len(line) > 0):
                    
                    # Additional check: if we're still in session header and this looks like a value, skip it
                    if in_session_header and (line.isdigit() or line in ['leader']):
                        logger.info(f"  -> SKIPPING (session value): '{line}'")
                        continue
                    
                    logger.info(f"  -> PLAYER NAME: '{line}'")
                    in_session_header = False  # We're definitely past session header now
                    
                    # Clean up player name
                    player_name = line.replace("(Leader)", "").strip()
                    if player_name and len(player_name) > 1:  # Must be more than 1 char
                        current_player = player_name
                        players[current_player] = {}
                        logger.info(f"    -> Added player: '{current_player}'")
                else:
                    logger.info(f"  -> IGNORED: '{line}'")
        
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
