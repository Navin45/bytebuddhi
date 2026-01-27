"""User quota management domain service.

This service manages user quota enforcement and tracking,
ensuring fair usage across the platform.

Note: This is a simplified quota service. The User model currently
only has usage_quota (limit). For full quota tracking, add quota_used
and quota_reset_at fields to the User model and database.
"""

from datetime import datetime
from typing import Optional

from app.domain.models.user import User


class QuotaManagementService:
    """Domain service for user quota management.
    
    This service encapsulates business rules around user quotas.
    Currently simplified to work with existing User model.
    """

    @staticmethod
    def can_user_make_request(user: User, cost: int = 1) -> bool:
        """Check if user has sufficient quota for a request.
        
        Business rule: Users must have available quota to make requests.
        
        Note: This is a simplified check. For production, implement
        quota_used tracking in the User model.
        
        Args:
            user: User entity
            cost: Cost of the request in quota units
            
        Returns:
            bool: True if user can make the request
        """
        # Simplified: just check if user is active
        # TODO: Implement proper quota tracking with quota_used field
        return user.is_active

    @staticmethod
    def calculate_request_cost(
        message_length: int,
        has_context: bool = False,
        is_streaming: bool = False,
    ) -> int:
        """Calculate quota cost for a request.
        
        Business rule: Different request types have different costs
        based on complexity and resource usage.
        
        Args:
            message_length: Length of user message
            has_context: Whether request includes context retrieval
            is_streaming: Whether response is streamed
            
        Returns:
            int: Quota cost for the request
        """
        # Base cost
        cost = 1
        
        # Add cost for long messages
        if message_length > 500:
            cost += 1
        if message_length > 1000:
            cost += 1
        
        # Context retrieval adds cost
        if has_context:
            cost += 2
        
        # Streaming is slightly more expensive
        if is_streaming:
            cost += 1
        
        return cost

    @staticmethod
    def get_quota_limit(user: User) -> int:
        """Get user's quota limit.
        
        Args:
            user: User entity
            
        Returns:
            int: User's quota limit
        """
        return user.usage_quota
