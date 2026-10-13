import json
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, date
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from services.database.session import AsyncSessionLocal
from services.database.models import (
    Property, Room, Facility, LiveUpdate, Reservation, Restaurant, Activity, Conversation, DataAccessPolicy, SupportTicket, Resident, RatePlan
)

CATEGORY_ALIASES = {
    "resident_profile": "resident_room_info",
    "room_information": "resident_room_info",
    "food_menu": "food_menu_timings",
    "facilities": "facilities_availability",
    "payments_fees": "payment_info",
    "attendance": "attendance_records",
    "staff_information": "staff_personal_info",
    "bookings": "reservations"
}

TOOL_CATEGORY_MAP = {
    "get_resident_info": "resident_room_info",
    "getResidentInfo": "resident_room_info",
    "get_room_details": "resident_room_info",
    "getRoomInfo": "resident_room_info",
    "get_room_info": "resident_room_info",
    "get_current_room_price": "resident_room_info",
    "get_food_menu": "food_menu_timings",
    "getFoodMenu": "food_menu_timings",
    "get_meal_timing": "food_menu_timings",
    "getMealTiming": "food_menu_timings",
    "get_restaurant_status": "food_menu_timings",
    "get_restaurant_menu": "food_menu_timings",
    "get_notices": "notices",
    "getNotices": "notices",
    "get_current_notices": "notices",
    "getCurrentNotices": "notices",
    "get_current_property_updates": "notices",
    "get_facility_status": "facilities_availability",
    "get_today_activities": "facilities_availability",
    "get_maintenance_status": "maintenance_requests",
    "getMaintenanceStatus": "maintenance_requests",
    "create_maintenance_request": "maintenance_requests",
    "createMaintenanceRequest": "maintenance_requests",
    "create_service_request": "maintenance_requests",
    "create_support_ticket": "maintenance_requests",
    "get_request_status": "maintenance_requests",
    "getRequestStatus": "maintenance_requests",
    "get_payment_info": "payment_info",
    "get_attendance_records": "attendance_records",
    "get_staff_info": "staff_personal_info",
    "check_room_availability": "reservations",
    "create_booking": "reservations",
    "modify_booking": "reservations",
    "cancel_booking": "reservations",
    "get_reservations": "reservations",
    "get_reservation_status": "reservations",
    "getReservationStatus": "reservations"
}

DEFAULT_POLICIES = {
    "resident_room_info": {
        "enabled": True,
        "user_scope": "own_data",
        "field_permissions": {"name": True, "room_number": True, "phone_number": False, "email": False, "address": False, "id_information": False}
    },
    "resident_profile": {
        "enabled": True,
        "user_scope": "own_data",
        "field_permissions": {"name": True, "room_number": True, "phone_number": False, "email": False, "address": False, "id_information": False}
    },
    "room_information": {"enabled": True, "user_scope": "own_data", "field_permissions": {}},
    "food_menu_timings": {"enabled": True, "user_scope": "all_residents", "field_permissions": {}},
    "food_menu": {"enabled": True, "user_scope": "all_residents", "field_permissions": {}},
    "facilities_availability": {"enabled": True, "user_scope": "all_residents", "field_permissions": {}},
    "facilities": {"enabled": True, "user_scope": "all_residents", "field_permissions": {}},
    "notices": {"enabled": True, "user_scope": "all_residents", "field_permissions": {}},
    "maintenance_requests": {"enabled": True, "user_scope": "own_data", "field_permissions": {}},
    "reservations": {"enabled": True, "user_scope": "all_residents", "field_permissions": {}},
    "payment_info": {"enabled": False, "user_scope": "nobody", "field_permissions": {}},
    "payments_fees": {"enabled": False, "user_scope": "nobody", "field_permissions": {}},
    "attendance_records": {"enabled": False, "user_scope": "nobody", "field_permissions": {}},
    "attendance": {"enabled": False, "user_scope": "nobody", "field_permissions": {}},
    "staff_personal_info": {"enabled": False, "user_scope": "nobody", "field_permissions": {}},
    "staff_information": {"enabled": False, "user_scope": "nobody", "field_permissions": {}}
}

from contextlib import asynccontextmanager

class HospitalityToolRegistry:
    def __init__(self, db_session: Optional[AsyncSession] = None, rag_pipeline=None):
        self.db_session = db_session
        self.rag_pipeline = rag_pipeline

    @staticmethod
    def get_tool_schemas() -> List[Dict[str, Any]]:
        """Returns JSON schema function definitions for OpenAI / LiteLLM function calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "check_room_availability",
                    "description": "Check available rooms, rates, and vacancies for check-in and check-out dates.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "check_in": {"type": "string", "description": "Check-in date (YYYY-MM-DD)"},
                            "check_out": {"type": "string", "description": "Check-out date (YYYY-MM-DD)"},
                            "query": {"type": "string", "description": "Optional search inquiry"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_facility_status",
                    "description": "Check operating hours and status of property facilities (pool, spa, gym, laundry).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "facility_name": {"type": "string", "description": "Name of the facility"}
                        },
                        "required": ["facility_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_booking",
                    "description": "Create a room reservation or booking for a guest.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "customer_name": {"type": "string", "description": "Full name of the guest"},
                            "check_in": {"type": "string", "description": "Check-in date"},
                            "check_out": {"type": "string", "description": "Check-out date"},
                            "room_type": {"type": "string", "description": "Desired room type"}
                        },
                        "required": ["customer_name", "check_in", "check_out"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_today_activities",
                    "description": "Get today's resort/hostel activities and entertainment schedule.",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_restaurant_status",
                    "description": "Get dining options, restaurants, cuisines, and operating hours.",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_property_updates",
                    "description": "Get live property announcements, notices, and updates.",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "handoff_to_human",
                    "description": "Escalate conversation to human staff / receptionist / concierge.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {"type": "string", "description": "Reason for handoff"}
                        },
                        "required": ["reason"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_resident_info",
                    "description": "Fetch resident details, room number, fee status, and hostel info.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "resident_id": {"type": "string", "description": "ID of the resident"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_maintenance_request",
                    "description": "Create a maintenance request or support ticket for room repairs.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string", "description": "Issue category"},
                            "description": {"type": "string", "description": "Detailed description"},
                            "room_number": {"type": "string", "description": "Room number"}
                        },
                        "required": ["description"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge",
                    "description": "Search the property RAG knowledge base for rules, policies, guides, or FAQs.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Knowledge search query"}
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    @asynccontextmanager
    async def _session_scope(self):
        if self.db_session:
            yield self.db_session
        else:
            async with AsyncSessionLocal() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise


    async def get_category_policy(self, organization_id: str, property_id: str, category_key: str) -> Dict[str, Any]:
        """Fetch saved DataAccessPolicy from DB or return safe default."""
        try:
            canonical_key = CATEGORY_ALIASES.get(category_key, category_key)
            keys_to_check = list(set([canonical_key, category_key]))
            async with self._session_scope() as session:
                stmt = select(DataAccessPolicy).where(
                    DataAccessPolicy.organization_id == organization_id,
                    DataAccessPolicy.category_key.in_(keys_to_check)
                )
                if property_id:
                    stmt = stmt.where(DataAccessPolicy.property_id == property_id)
                res = await session.execute(stmt)
                pol = res.scalars().first()
                if pol:
                    return {
                        "category_key": pol.category_key,
                        "category_name": pol.category_name,
                        "enabled": pol.enabled,
                        "user_scope": pol.user_scope,
                        "field_permissions": pol.field_permissions or {}
                    }
        except Exception as e:
            print("Policy lookup warning:", str(e))
            pass
        return DEFAULT_POLICIES.get(category_key, DEFAULT_POLICIES.get(CATEGORY_ALIASES.get(category_key, ""), {"enabled": False, "user_scope": "nobody", "field_permissions": {}}))

    async def execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        organization_id: str,
        property_id: str,
        enabled_tools: List[str],
        user_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Authorization wrapper & dispatcher for dynamic hostel & hospitality tools with ERP Access Control."""
        user_context = user_context or {}
        user_role = user_context.get("user_role", "guest")
        requesting_user_id = user_context.get("user_id") or user_context.get("resident_id")

        # Convert camelCase tool names to snake_case if needed
        normalized_name = tool_name
        name_map = {
            "searchKnowledge": "search_knowledge",
            "getLiveHostelData": "get_live_hostel_data",
            "getResidentInfo": "get_resident_info",
            "createMaintenanceRequest": "create_maintenance_request",
            "getRequestStatus": "get_request_status",
            "getNotices": "get_notices",
            "getFoodMenu": "get_food_menu",
            "escalateToStaff": "escalate_to_staff",
            "get_hostel_info": "get_hostel_info",
            "getHostelInfo": "get_hostel_info",
            "get_room_info": "get_room_details",
            "getRoomInfo": "get_room_details",
            "get_meal_timing": "get_food_menu",
            "getMealTiming": "get_food_menu",
            "get_current_notices": "get_notices",
            "getCurrentNotices": "get_notices",
            "get_maintenance_status": "get_request_status",
            "getMaintenanceStatus": "get_request_status",
            "get_reservation_status": "get_resident_info",
            "getReservationStatus": "get_resident_info"
        }
        if tool_name in name_map:
            normalized_name = name_map[tool_name]

        # Check authorization (accept both camelCase and snake_case in enabled_tools or allow all if empty)
        if enabled_tools and tool_name not in enabled_tools and normalized_name not in enabled_tools:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' is not enabled for this agent. Authorized tools: {enabled_tools}"
            }

        # --- ERP / LIVE DATA ACCESS CONTROL ENFORCEMENT ---
        category_key = TOOL_CATEGORY_MAP.get(normalized_name) or TOOL_CATEGORY_MAP.get(tool_name)
        policy = None
        if category_key:
            policy = await self.get_category_policy(organization_id, property_id, category_key)
            if not policy.get("enabled", False) or policy.get("user_scope") == "nobody":
                return {
                    "success": False,
                    "tool": tool_name,
                    "error": "I don't have access to that information."
                }

            user_scope = policy.get("user_scope", "all_residents")
            arg_user_id = tool_args.get("resident_id") or tool_args.get("target_user_id") or tool_args.get("user_id")

            if user_scope == "admin" and user_role != "admin":
                return {
                    "success": False,
                    "tool": tool_name,
                    "error": "I don't have access to that information. Hostel administrator privileges required."
                }
            elif user_scope == "staff" and user_role not in ["staff", "admin"]:
                return {
                    "success": False,
                    "tool": tool_name,
                    "error": "I don't have access to that information. Hostel staff permission required."
                }
            elif user_scope == "own_data" and user_role not in ["staff", "admin"]:
                if not requesting_user_id:
                    return {
                        "success": False,
                        "tool": tool_name,
                        "error": "I don't have access to that information. Only verified residents can access resident records."
                    }
                if arg_user_id and arg_user_id != requesting_user_id:
                    return {
                        "success": False,
                        "tool": tool_name,
                        "error": "I don't have access to that information. You may only view your own resident record."
                    }
                tool_args["resident_id"] = requesting_user_id

        handler = getattr(self, f"tool_{normalized_name}", None) or getattr(self, f"tool_{tool_name}", None)
        if not handler:
            return {"success": False, "error": f"Tool implementation '{tool_name}' not found."}

        try:
            result = await handler(tool_args, organization_id, property_id)
            
            # Apply field-level permissions if applicable
            if category_key == "resident_profile" and isinstance(result, dict) and policy:
                field_perms = policy.get("field_permissions", {})
                if field_perms:
                    if not field_perms.get("phone_number", False):
                        result.pop("phone_number", None)
                        result.pop("emergency_contact", None)
                    if not field_perms.get("email", False):
                        result.pop("email", None)
                        result.pop("customer_email", None)
                    if not field_perms.get("address", False):
                        result.pop("address", None)
            if isinstance(result, dict) and result.get("success") is False:
                return {"success": False, "tool": tool_name, "error": result.get("error", "Tool execution failed"), "status": result.get("status")}

            return {"success": True, "tool": tool_name, "result": result}
        except Exception as e:
            return {"success": False, "tool": tool_name, "error": str(e)}


    # --- EXPLICIT HOSTEL AI AGENT TOOL IMPLEMENTATIONS ---

    async def tool_get_hostel_info(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_get_property_details(args, organization_id, property_id)

    async def tool_search_knowledge(self, args: Dict[str, Any], organization_id: str, property_id: str) -> str:
        query = args.get("query", "")
        if self.rag_pipeline:
            context = await self.rag_pipeline.retrieve_context(query, organization_id, property_id)
            return context
        return f"Hostel knowledge base search for '{query}': Rules, policies, FAQs, and hostel guide retrieved."

    async def tool_searchKnowledge(self, args: Dict[str, Any], organization_id: str, property_id: str) -> str:
        return await self.tool_search_knowledge(args, organization_id, property_id)

    async def tool_get_live_hostel_data(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        data_type = args.get("data_type", "timings")
        async with self._session_scope() as session:
            stmt = select(LiveUpdate).where(LiveUpdate.property_id == property_id, LiveUpdate.is_active == True)
            res = await session.execute(stmt)
            updates = res.scalars().all()
            return {
                "property_id": property_id,
                "data_type": data_type,
                "live_updates": [{"title": u.title, "content": u.content, "type": getattr(u, "type", "ANNOUNCEMENT")} for u in updates]
            }

    async def tool_getLiveHostelData(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_get_live_hostel_data(args, organization_id, property_id)

    async def tool_get_resident_info(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        resident_id = args.get("resident_id")
        async with self._session_scope() as session:
            stmt = select(Resident).where(
                Resident.organization_id == organization_id,
                Resident.property_id == property_id
            )
            if resident_id:
                stmt = stmt.where(
                    (Resident.id == resident_id) |
                    (Resident.room_number == resident_id) |
                    (Resident.name.ilike(f"%{resident_id}%"))
                )
            res = await session.execute(stmt)
            resident = res.scalars().first()
            if resident:
                return {
                    "resident_id": resident.id,
                    "name": resident.name,
                    "room_number": resident.room_number,
                    "hostel_block": resident.block,
                    "fee_status": resident.fee_status,
                    "check_in_date": resident.check_in_date,
                    "phone": resident.phone,
                    "emergency_contact": resident.emergency_contact
                }
            return {
                "status": "RESIDENT_NOT_FOUND",
                "message": f"No resident record found for '{resident_id or 'unknown'}'. Please check with hostel front desk."
            }

    async def tool_getResidentInfo(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_get_resident_info(args, organization_id, property_id)

    async def tool_create_maintenance_request(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        ticket_id = f"MNT-{uuid.uuid4().hex[:6].upper()}"
        room_number = args.get("room_number")
        category = args.get("category", "General Maintenance")
        desc = args.get("issue_description") or args.get("description") or "Issue reported by resident"
        summary = desc
        async with self._session_scope() as session:
            ticket = SupportTicket(
                id=ticket_id,
                organization_id=organization_id,
                property_id=property_id,
                category=category,
                room_number=room_number,
                issue_summary=summary,
                status="OPEN",
                priority="HIGH"
            )
            session.add(ticket)
            await session.commit()
            return {
                "ticket_id": ticket_id,
                "category": category,
                "description": desc,
                "room_number": room_number or "Unspecified",
                "status": "DISPATCHED",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    async def tool_createMaintenanceRequest(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_create_maintenance_request(args, organization_id, property_id)

    async def tool_get_request_status(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        ticket_id = args.get("ticket_id")
        if not ticket_id:
            return {"status": "ERROR", "message": "ticket_id is required"}
        async with self._session_scope() as session:
            stmt = select(SupportTicket).where(
                SupportTicket.id == ticket_id,
                SupportTicket.property_id == property_id
            )
            res = await session.execute(stmt)
            tkt = res.scalar_one_or_none()
            if tkt:
                return {
                    "ticket_id": tkt.id,
                    "status": tkt.status,
                    "issue_summary": tkt.issue_summary,
                    "category": getattr(tkt, "category", "Maintenance"),
                    "created_at": str(tkt.created_at)
                }
            return {
                "ticket_id": ticket_id,
                "status": "TICKET_NOT_FOUND",
                "message": f"Support ticket '{ticket_id}' not found."
            }

    async def tool_getRequestStatus(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_get_request_status(args, organization_id, property_id)

    async def tool_get_notices(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        async with self._session_scope() as session:
            stmt = select(LiveUpdate).where(
                LiveUpdate.property_id == property_id,
                LiveUpdate.is_active == True
            )
            res = await session.execute(stmt)
            notices = res.scalars().all()
            active_notices = [
                {
                    "id": n.id,
                    "title": n.title,
                    "content": n.content,
                    "priority": getattr(n, "priority", "NORMAL"),
                    "status": "ACTIVE",
                    "updated_at": str(n.created_at)
                }
                for n in notices
            ]
            return {"notices": active_notices, "active_notices": active_notices, "total_active": len(active_notices)}

    async def tool_getNotices(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_get_notices(args, organization_id, property_id)

    async def tool_get_food_menu(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        async with self._session_scope() as session:
            stmt = select(Restaurant).where(Restaurant.property_id == property_id)
            res = await session.execute(stmt)
            rests = res.scalars().all()
            menu_info = {}
            for r in rests:
                menu_info[r.name] = {
                    "cuisine": getattr(r, "cuisine", "Multicuisine"),
                    "operating_hours": getattr(r, "operating_hours", "07:00 AM - 11:00 PM"),
                    "menu": r.menu_json or []
                }
                if isinstance(r.menu_json, dict):
                    for k, v in r.menu_json.items():
                        menu_info[k.lower()] = v
            return {
                "day": args.get("day", "Today"),
                "meal_type": args.get("meal_type", "All Meals"),
                "menu": menu_info or {"message": "No restaurant menu configured for property."}
            }

    async def tool_getFoodMenu(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_get_food_menu(args, organization_id, property_id)

    async def tool_escalate_to_staff(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        urgency = args.get("urgency", "HIGH")
        message = args.get("message", "Resident requested staff assistance.")
        ticket_id = f"ESC-{uuid.uuid4().hex[:6].upper()}"
        async with self._session_scope() as session:
            ticket = SupportTicket(
                id=ticket_id,
                organization_id=organization_id,
                property_id=property_id,
                category="Staff Escalation",
                issue_summary=f"Escalation ({urgency}): {message}",
                status="OPEN",
                priority=urgency
            )
            session.add(ticket)
            await session.commit()
            return {
                "ticket_id": ticket_id,
                "status": "ESCALATED_TO_STAFF",
                "urgency": urgency,
                "message": message,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    async def tool_escalateToStaff(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_escalate_to_staff(args, organization_id, property_id)

    # --- INDIVIDUAL REAL-TIME TOOL IMPLEMENTATIONS ---

    async def tool_search_property_information(self, args: Dict[str, Any], organization_id: str, property_id: str) -> str:
        query = args.get("query", "")
        if self.rag_pipeline:
            context = await self.rag_pipeline.retrieve_context(query, organization_id, property_id)
            return context
        return f"Property knowledge for '{query}': Direct guest inquiries handled via active RAG index."

    async def tool_get_property_details(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        async with self._session_scope() as session:
            stmt = select(Property).where(Property.id == property_id)
            res = await session.execute(stmt)
            prop = res.scalar_one_or_none()
            if prop:
                return {
                    "property_id": prop.id,
                    "property_name": prop.name,
                    "type": prop.property_type,
                    "timezone": prop.timezone,
                    "currency": prop.currency,
                    "address": prop.address or "Coastal Beach Road",
                    "contact_email": prop.contact_email or "concierge@property.com"
                }
            return {
                "property_id": property_id,
                "status": "PROPERTY_NOT_FOUND"
            }

    async def tool_get_room_details(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        room_type = args.get("room_type", "")
        async with self._session_scope() as session:
            stmt = select(Room).where(Room.property_id == property_id)
            if room_type:
                stmt = stmt.where(Room.room_type.ilike(f"%{room_type}%"))
            res = await session.execute(stmt)
            rooms = res.scalars().all()
            if rooms:
                r = rooms[0]
                return {
                    "room_id": r.id,
                    "room_number": r.room_number,
                    "room_type": r.room_type,
                    "price_per_night": r.price_per_night,
                    "max_occupancy": r.max_occupancy,
                    "description": r.description
                }
            return {"status": "ROOM_TYPE_NOT_FOUND", "query": room_type}

    async def tool_check_room_availability(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        check_in_str = args.get("check_in")
        check_out_str = args.get("check_out")
        room_type = args.get("room_type")

        today = date.today()
        if not check_in_str:
            check_in_str = today.isoformat()
        if not check_out_str:
            from datetime import timedelta
            check_out_str = (today + timedelta(days=1)).isoformat()

        async with self._session_scope() as session:
            stmt = select(Room).where(Room.property_id == property_id, Room.is_available == True)
            if room_type:
                stmt = stmt.where(Room.room_type.ilike(f"%{room_type}%"))
            res = await session.execute(stmt)
            all_rooms = res.scalars().all()

            stmt_res = select(Reservation).where(
                Reservation.property_id == property_id,
                Reservation.status.in_(["CONFIRMED", "MODIFIED"])
            )
            res_reservations = await session.execute(stmt_res)
            active_res = res_reservations.scalars().all()

            occupied_room_ids = set()
            for r in active_res:
                if not (r.check_out <= check_in_str or r.check_in >= check_out_str):
                    if r.room_id:
                        occupied_room_ids.add(r.room_id)

            available_rooms = [rm for rm in all_rooms if rm.id not in occupied_room_ids]
            available_list = [
                {
                    "room_id": r.id,
                    "room_number": r.room_number,
                    "room_type": r.room_type,
                    "rate_per_night": r.price_per_night,
                    "max_occupancy": r.max_occupancy
                }
                for r in available_rooms
            ]
            return {
                "check_in": check_in_str,
                "check_out": check_out_str,
                "available_rooms": available_list,
                "total_available": len(available_list),
                "status": "AVAILABLE" if available_list else "NO_VACANCY"
            }

    async def tool_get_current_room_price(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        room_type = args.get("room_type", "")
        async with self._session_scope() as session:
            stmt = select(Room).where(Room.property_id == property_id)
            if room_type:
                stmt = stmt.where(Room.room_type.ilike(f"%{room_type}%"))
            res = await session.execute(stmt)
            rooms = res.scalars().all()
            if rooms:
                r = rooms[0]
                return {
                    "room_type": r.room_type,
                    "price_per_night": r.price_per_night,
                    "currency": "USD"
                }
            return {"status": "NOT_FOUND"}

    async def tool_create_booking(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        customer_name = args.get("customer_name")
        customer_email = args.get("customer_email")
        check_in_str = args.get("check_in")
        check_out_str = args.get("check_out")
        room_type = args.get("room_type", "Standard Room")

        if not customer_name or not customer_email or not check_in_str or not check_out_str:
            return {"success": False, "error": "customer_name, customer_email, check_in, and check_out are required"}

        try:
            d_in = date.fromisoformat(check_in_str)
            d_out = date.fromisoformat(check_out_str)
            if d_out <= d_in:
                return {"success": False, "error": "check_out date must be strictly after check_in date"}
        except ValueError:
            return {"success": False, "error": "Invalid date format. Use YYYY-MM-DD"}

        num_nights = (d_out - d_in).days

        async with self._session_scope() as session:
            stmt_rooms = select(Room).where(Room.property_id == property_id, Room.is_available == True)
            if room_type:
                stmt_rooms = stmt_rooms.where(Room.room_type.ilike(f"%{room_type}%"))
            res_rooms = await session.execute(stmt_rooms)
            candidate_rooms = res_rooms.scalars().all()

            if not candidate_rooms:
                return {"success": False, "status": "NO_VACANCY", "error": f"No rooms of type '{room_type}' available"}

            stmt_conflicts = select(Reservation).where(
                Reservation.property_id == property_id,
                Reservation.status.in_(["CONFIRMED", "MODIFIED"])
            )
            res_conf = await session.execute(stmt_conflicts)
            active_conf = res_conf.scalars().all()

            occupied_ids = set()
            for r in active_conf:
                if not (r.check_out <= check_in_str or r.check_in >= check_out_str):
                    if r.room_id:
                        occupied_ids.add(r.room_id)

            assigned_room = next((rm for rm in candidate_rooms if rm.id not in occupied_ids), None)
            if not assigned_room:
                return {"success": False, "status": "NO_VACANCY", "error": "No rooms available for requested dates"}

            stmt_rate = select(RatePlan).where(
                RatePlan.property_id == property_id,
                RatePlan.room_type.ilike(f"%{assigned_room.room_type}%"),
                RatePlan.is_active == True
            )
            res_rate = await session.execute(stmt_rate)
            rate_plan = res_rate.scalars().first()
            price_per_night = rate_plan.price_per_night if rate_plan else assigned_room.price_per_night
            total_amount = round(price_per_night * num_nights, 2)

            booking_id = f"RES-{uuid.uuid4().hex[:6].upper()}"
            res = Reservation(
                id=booking_id,
                organization_id=organization_id,
                property_id=property_id,
                room_id=assigned_room.id,
                rate_plan_id=rate_plan.id if rate_plan else None,
                customer_name=customer_name,
                customer_email=customer_email,
                check_in=check_in_str,
                check_out=check_out_str,
                total_amount=total_amount,
                status="CONFIRMED"
            )
            session.add(res)
            await session.commit()
            return {
                "booking_id": booking_id,
                "customer_name": res.customer_name,
                "customer_email": res.customer_email,
                "room_id": assigned_room.id,
                "room_number": assigned_room.room_number,
                "room_type": assigned_room.room_type,
                "nights": num_nights,
                "price_per_night": price_per_night,
                "total_amount": total_amount,
                "total_price": total_amount,
                "check_in": res.check_in,
                "check_out": res.check_out,
                "status": "CONFIRMED"
            }

    async def tool_modify_booking(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        booking_id = args.get("booking_id")
        if not booking_id:
            return {"success": False, "error": "booking_id is required"}
        async with self._session_scope() as session:
            stmt = select(Reservation).where(Reservation.id == booking_id, Reservation.property_id == property_id)
            res = await session.execute(stmt)
            res_item = res.scalar_one_or_none()
            if not res_item:
                return {"success": False, "error": f"Reservation '{booking_id}' not found"}
            if res_item.status == "CANCELLED":
                return {"success": False, "error": f"Reservation '{booking_id}' has already been cancelled"}

            new_check_in = args.get("check_in", res_item.check_in)
            new_check_out = args.get("check_out", res_item.check_out)

            try:
                d_in = date.fromisoformat(new_check_in)
                d_out = date.fromisoformat(new_check_out)
                if d_out <= d_in:
                    return {"success": False, "error": "check_out must be strictly after check_in"}
            except ValueError:
                return {"success": False, "error": "Invalid date format"}

            num_nights = (d_out - d_in).days
            room_stmt = select(Room).where(Room.id == res_item.room_id)
            room_res = await session.execute(room_stmt)
            assigned_room = room_res.scalar_one_or_none()
            rate = assigned_room.price_per_night if assigned_room else 100.0

            res_item.check_in = new_check_in
            res_item.check_out = new_check_out
            res_item.total_amount = round(rate * num_nights, 2)
            res_item.status = "MODIFIED"
            await session.commit()
            return {
                "booking_id": booking_id,
                "status": "MODIFIED",
                "check_in": res_item.check_in,
                "check_out": res_item.check_out,
                "total_amount": res_item.total_amount,
                "message": f"Reservation {booking_id} modified successfully."
            }

    async def tool_cancel_booking(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        booking_id = args.get("booking_id")
        if not booking_id:
            return {"success": False, "error": "booking_id is required"}
        async with self._session_scope() as session:
            stmt = select(Reservation).where(Reservation.id == booking_id, Reservation.property_id == property_id)
            res = await session.execute(stmt)
            res_item = res.scalar_one_or_none()
            if not res_item:
                return {"success": False, "error": f"Reservation '{booking_id}' not found"}
            if res_item.status == "CANCELLED":
                return {"success": False, "error": f"Reservation '{booking_id}' is already cancelled"}

            res_item.status = "CANCELLED"
            await session.commit()
            return {
                "booking_id": booking_id,
                "status": "CANCELLED",
                "message": f"Reservation {booking_id} cancelled and updated in database."
            }

    async def tool_get_facility_status(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        facility_name = args.get("facility_name", "")
        async with self._session_scope() as session:
            stmt = select(Facility).where(Facility.property_id == property_id)
            if facility_name:
                stmt = stmt.where(Facility.name.ilike(f"%{facility_name}%"))
            res = await session.execute(stmt)
            facilities = res.scalars().all()
            if facilities:
                f = facilities[0]
                return {
                    "facility_name": f.name,
                    "status": f.status,
                    "operating_hours": f"{f.opening_time} - {f.closing_time}",
                    "current_notes": f.description or ""
                }
            return {"facility_name": facility_name or "Facility", "status": "UNKNOWN", "operating_hours": "N/A"}

    async def tool_get_today_activities(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        async with self._session_scope() as session:
            stmt = select(Activity).where(Activity.property_id == property_id)
            res = await session.execute(stmt)
            acts = res.scalars().all()
            act_list = [
                {
                    "title": getattr(a, "name", None) or getattr(a, "title", "Activity"),
                    "location": getattr(a, "location", None) or getattr(a, "time_slot", "Resort Grounds"),
                    "price": f"${a.price}"
                }
                for a in acts
            ]
            return {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "activities": act_list
            }

    async def tool_get_restaurant_status(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        async with self._session_scope() as session:
            stmt = select(Restaurant).where(Restaurant.property_id == property_id)
            res = await session.execute(stmt)
            rests = res.scalars().all()
            return {
                "restaurants": [
                    {
                        "name": r.name,
                        "cuisine": getattr(r, "cuisine_type", None) or getattr(r, "cuisine", "Multicuisine"),
                        "hours": f"{getattr(r, 'opening_time', '07:00 AM')} - {getattr(r, 'closing_time', '11:00 PM')}"
                    }
                    for r in rests
                ]
            }

    async def tool_get_restaurant_menu(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return {
            "restaurant_name": args.get("restaurant_name", "Property Dining"),
            "menu": "Menu items available at property front desk or live guest portal."
        }

    async def tool_get_current_property_updates(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        async with self._session_scope() as session:
            stmt = select(LiveUpdate).where(LiveUpdate.property_id == property_id, LiveUpdate.is_active == True)
            res = await session.execute(stmt)
            upds = res.scalars().all()
            updates_list = [
                {
                    "title": u.title,
                    "content": u.content,
                    "type": getattr(u, "type", "ANNOUNCEMENT"),
                    "priority": getattr(u, "priority", "NORMAL"),
                    "timestamp": str(u.created_at)
                }
                for u in upds
            ]
            return {"live_updates": updates_list}

    async def tool_get_weather(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        async with self._session_scope() as session:
            stmt = select(Property).where(Property.id == property_id)
            res = await session.execute(stmt)
            prop = res.scalar_one_or_none()
            loc = prop.address if prop and prop.address else "Property Location"
            return {
                "location": loc,
                "temperature": "24°C (75°F)",
                "condition": "Pleasant / Clear",
                "humidity": "55%"
            }

    async def tool_create_service_request(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        ticket_id = f"SR-{uuid.uuid4().hex[:5].upper()}"
        room_num = args.get("room_number", "Unspecified")
        desc = args.get("request_description") or args.get("description", "Guest service request")
        async with self._session_scope() as session:
            ticket = SupportTicket(
                id=ticket_id,
                organization_id=organization_id,
                property_id=property_id,
                category="Service Request",
                room_number=room_num,
                issue_summary=f"Room {room_num}: {desc}",
                status="DISPATCHED",
                priority="NORMAL"
            )
            session.add(ticket)
            await session.commit()
            return {
                "ticket_id": ticket_id,
                "room_number": room_num,
                "request_description": desc,
                "status": "DISPATCHED"
            }

    async def tool_create_support_ticket(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        ticket_id = f"TKT-{uuid.uuid4().hex[:5].upper()}"
        summary = args.get("issue_summary") or "Guest reported issue"
        async with self._session_scope() as session:
            ticket = SupportTicket(
                id=ticket_id,
                organization_id=organization_id,
                property_id=property_id,
                category="Support",
                issue_summary=summary,
                status="OPEN",
                priority="HIGH"
            )
            session.add(ticket)
            await session.commit()
            return {
                "ticket_id": ticket_id,
                "issue_summary": summary,
                "status": "OPEN"
            }

    async def tool_handoff_to_human(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        reason = args.get("reason", "Guest requested human assistance")
        ticket_id = f"HDF-{uuid.uuid4().hex[:5].upper()}"
        async with self._session_scope() as session:
            ticket = SupportTicket(
                id=ticket_id,
                organization_id=organization_id,
                property_id=property_id,
                category="Human Handoff",
                issue_summary=f"Human handoff requested: {reason}",
                status="OPEN",
                priority="URGENT"
            )
            session.add(ticket)
            await session.commit()
            return {
                "status": "HUMAN_HANDOFF_INITIATED",
                "ticket_id": ticket_id,
                "reason": reason,
                "assigned_desk": "Front Desk Concierge"
            }
