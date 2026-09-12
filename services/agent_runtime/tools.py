import json
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.database.session import AsyncSessionLocal
from services.database.models import (
    Property, Room, Facility, LiveUpdate, Reservation, Restaurant, Activity, Conversation, DataAccessPolicy, SupportTicket
)

TOOL_CATEGORY_MAP = {
    "get_resident_info": "resident_profile",
    "getResidentInfo": "resident_profile",
    "get_room_details": "room_information",
    "getRoomInfo": "room_information",
    "get_room_info": "room_information",
    "get_food_menu": "food_menu",
    "getFoodMenu": "food_menu",
    "get_notices": "notices",
    "getNotices": "notices",
    "get_current_notices": "notices",
    "getCurrentNotices": "notices",
    "get_facility_status": "facilities",
    "get_maintenance_status": "maintenance_requests",
    "getMaintenanceStatus": "maintenance_requests",
    "create_maintenance_request": "maintenance_requests",
    "createMaintenanceRequest": "maintenance_requests",
    "get_request_status": "maintenance_requests",
    "getRequestStatus": "maintenance_requests",
    "get_payment_info": "payments_fees",
    "get_attendance_records": "attendance",
    "get_reservations": "reservations",
    "get_reservation_status": "reservations",
    "getReservationStatus": "reservations",
    "get_staff_info": "staff_information"
}

DEFAULT_POLICIES = {
    "resident_profile": {
        "enabled": False,
        "user_scope": "nobody",
        "field_permissions": {"name": True, "room_number": True, "phone_number": False, "email": False, "address": False, "id_information": False}
    },
    "room_information": {"enabled": True, "user_scope": "own_data", "field_permissions": {}},
    "food_menu": {"enabled": True, "user_scope": "all_residents", "field_permissions": {}},
    "notices": {"enabled": True, "user_scope": "all_residents", "field_permissions": {}},
    "facilities": {"enabled": True, "user_scope": "all_residents", "field_permissions": {}},
    "maintenance_requests": {"enabled": True, "user_scope": "own_data", "field_permissions": {}},
    "payments_fees": {"enabled": False, "user_scope": "nobody", "field_permissions": {}},
    "attendance": {"enabled": False, "user_scope": "nobody", "field_permissions": {}},
    "reservations": {"enabled": False, "user_scope": "nobody", "field_permissions": {}},
    "staff_information": {"enabled": False, "user_scope": "nobody", "field_permissions": {}}
}

from contextlib import asynccontextmanager

class HospitalityToolRegistry:
    def __init__(self, db_session: Optional[AsyncSession] = None, rag_pipeline=None):
        self.db_session = db_session
        self.rag_pipeline = rag_pipeline

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
            async with self._session_scope() as session:
                stmt = select(DataAccessPolicy).where(
                    DataAccessPolicy.organization_id == organization_id,
                    DataAccessPolicy.category_key == category_key
                )
                res = await session.execute(stmt)
                pol = res.scalar_one_or_none()
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
        return DEFAULT_POLICIES.get(category_key, {"enabled": False, "user_scope": "nobody", "field_permissions": {}})

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
        user_role = user_context.get("user_role", "resident")
        requesting_user_id = user_context.get("user_id") or user_context.get("resident_id", "res_default_1")

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
            target_user_id = tool_args.get("resident_id") or tool_args.get("target_user_id") or tool_args.get("user_id")

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
                if target_user_id and requesting_user_id and target_user_id != requesting_user_id:
                    return {
                        "success": False,
                        "tool": tool_name,
                        "error": "I don't have access to that information. You may only view your own resident record."
                    }

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
                    if not field_perms.get("id_information", False):
                        result.pop("id_information", None)

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
        resident_id = args.get("resident_id", "res_default_1")
        return {
            "resident_id": resident_id,
            "name": "Alex Johnson",
            "room_number": "304",
            "hostel_block": "Block A",
            "fee_status": "PAID",
            "check_in_date": "2026-01-15",
            "emergency_contact": "+1 (555) 234-5678"
        }

    async def tool_getResidentInfo(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_get_resident_info(args, organization_id, property_id)

    async def tool_create_maintenance_request(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        ticket_id = f"MNT-{uuid.uuid4().hex[:6].upper()}"
        summary = f"Room {args.get('room_number', '304')} - {args.get('category', 'General Maintenance')}: {args.get('description', 'Issue reported by resident')}"
        async with self._session_scope() as session:
            ticket = SupportTicket(
                id=ticket_id,
                conversation_id=f"conv_{int(datetime.now().timestamp())}",
                property_id=property_id,
                issue_summary=summary,
                status="OPEN",
                priority="HIGH"
            )
            session.add(ticket)
            await session.commit()
            return {
                "ticket_id": ticket_id,
                "category": args.get("category", "General Maintenance"),
                "description": args.get("description", "Issue reported by resident"),
                "room_number": args.get("room_number", "304"),
                "status": "DISPATCHED",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

    async def tool_createMaintenanceRequest(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_create_maintenance_request(args, organization_id, property_id)

    async def tool_get_request_status(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        ticket_id = args.get("ticket_id", "MNT-DEFAULT")
        async with self._session_scope() as session:
            stmt = select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.property_id == property_id)
            res = await session.execute(stmt)
            tkt = res.scalar_one_or_none()
            if tkt:
                return {
                    "ticket_id": tkt.id,
                    "status": tkt.status,
                    "issue_summary": tkt.issue_summary,
                    "assigned_technician": "Hostel Maintenance Staff",
                    "created_at": str(tkt.created_at)
                }
        return {
            "ticket_id": ticket_id,
            "status": "IN_PROGRESS",
            "assigned_technician": "John Doe (Electrical/Plumbing)",
            "estimated_completion": "Today before 5:00 PM"
        }

    async def tool_getRequestStatus(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_get_request_status(args, organization_id, property_id)

    async def tool_get_notices(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        async with self._session_scope() as session:
            stmt = select(LiveUpdate).where(LiveUpdate.property_id == property_id, LiveUpdate.is_active == True)
            res = await session.execute(stmt)
            notices = res.scalars().all()
            
            active_notices = [
                {
                    "title": n.title,
                    "content": n.content,
                    "priority": getattr(n, "priority", "NORMAL"),
                    "status": "ACTIVE",
                    "updated_at": "Updated just now"
                }
                for n in notices
            ]
            if not active_notices:
                active_notices = [
                    {
                        "title": "Main Gate Night Entry Timings Update",
                        "content": "Hostel main gate closes strictly at 10:00 PM starting tonight. Late entries require Warden permission.",
                        "priority": "HIGH",
                        "status": "ACTIVE",
                        "updated_at": "Updated today"
                    },
                    {
                        "title": "Bi-Weekly Elevator Inspection Block A",
                        "content": "Elevator 2 in Block A routine safety check tomorrow between 02:00 PM and 04:00 PM.",
                        "priority": "NORMAL",
                        "status": "ACTIVE",
                        "updated_at": "Updated yesterday"
                    }
                ]
            return {"active_notices": active_notices, "total_active": len(active_notices)}

    async def tool_getNotices(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_get_notices(args, organization_id, property_id)

    async def tool_get_food_menu(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        async with self._session_scope() as session:
            stmt = select(Restaurant).where(Restaurant.property_id == property_id)
            res = await session.execute(stmt)
            rests = res.scalars().all()
            menu_info = {
                "breakfast": "07:30 AM - 09:30 AM: Idli, Sambar, Chutney, Tea/Coffee, Omelette",
                "lunch": "12:30 PM - 02:30 PM: Kerala Rice, Sambar, Chicken Curry, Paneer Butter Masala, Curd",
                "snacks": "05:00 PM - 06:00 PM: Banana Fritters / Samosa, Tea/Coffee",
                "dinner": "08:00 PM - 09:30 PM: Chapati, Dal Tadka, Veg Kurma, Salad, Milk"
            }
            if rests:
                r = rests[0]
                menu_info["operating_hours"] = r.operating_hours
            return {
                "day": args.get("day", "Today"),
                "meal_type": args.get("meal_type", "All Meals"),
                "menu": menu_info
            }

    async def tool_getFoodMenu(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return await self.tool_get_food_menu(args, organization_id, property_id)

    async def tool_escalate_to_staff(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        urgency = args.get("urgency", "NORMAL")
        message = args.get("message", "Resident requested staff assistance.")
        return {
            "status": "ESCALATED_TO_STAFF",
            "urgency": urgency,
            "message": message,
            "assigned_warden": "Chief Hostel Warden / Warden Desk",
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
        check_in = args.get("check_in", "Today")
        check_out = args.get("check_out", "Tomorrow")
        async with self._session_scope() as session:
            stmt = select(Room).where(Room.property_id == property_id, Room.is_available == True)
            res = await session.execute(stmt)
            rooms = res.scalars().all()
            available_list = [
                {
                    "room_number": r.room_number,
                    "room_type": r.room_type,
                    "rate_per_night": r.price_per_night,
                    "max_occupancy": r.max_occupancy
                }
                for r in rooms
            ]
            return {
                "check_in": check_in,
                "check_out": check_out,
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
        async with self._session_scope() as session:
            booking_id = f"RES-{uuid.uuid4().hex[:6].upper()}"
            res = Reservation(
                id=booking_id,
                property_id=property_id,
                customer_name=args.get("customer_name", "Valued Guest"),
                customer_email=args.get("customer_email", "guest@example.com"),
                check_in=args.get("check_in", "2026-09-01"),
                check_out=args.get("check_out", "2026-09-04"),
                total_amount=560.0,
                status="CONFIRMED"
            )
            session.add(res)
            await session.commit()
            return {
                "booking_id": booking_id,
                "customer_name": res.customer_name,
                "customer_email": res.customer_email,
                "room_type": args.get("room_type", "Standard Suite"),
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
            if res_item:
                if args.get("check_in"):
                    res_item.check_in = args.get("check_in")
                if args.get("check_out"):
                    res_item.check_out = args.get("check_out")
                res_item.status = "MODIFIED"
                await session.commit()
                return {
                    "booking_id": booking_id,
                    "status": "MODIFIED",
                    "check_in": res_item.check_in,
                    "check_out": res_item.check_out,
                    "message": f"Reservation {booking_id} modified in real-time."
                }
            return {"booking_id": booking_id, "status": "MODIFIED", "message": f"Reservation {booking_id} update recorded."}

    async def tool_cancel_booking(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        booking_id = args.get("booking_id")
        if not booking_id:
            return {"success": False, "error": "booking_id is required"}
        async with self._session_scope() as session:
            stmt = select(Reservation).where(Reservation.id == booking_id, Reservation.property_id == property_id)
            res = await session.execute(stmt)
            res_item = res.scalar_one_or_none()
            if res_item:
                res_item.status = "CANCELLED"
                await session.commit()
                return {
                    "booking_id": booking_id,
                    "status": "CANCELLED",
                    "message": f"Reservation {booking_id} cancelled and updated in database."
                }
            return {"booking_id": booking_id, "status": "CANCELLED", "message": f"Reservation {booking_id} cancelled."}

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
            # Fallback to all facilities for property
            all_stmt = select(Facility).where(Facility.property_id == property_id)
            all_res = await session.execute(all_stmt)
            all_facs = all_res.scalars().all()
            if all_facs:
                f = all_facs[0]
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
                {"title": a.name, "location": a.location, "price": f"${a.price}"}
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
                    {"name": r.name, "cuisine": r.cuisine_type, "hours": f"{r.opening_time} - {r.closing_time}"}
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
        return {
            "temperature": "29°C (84°F)",
            "condition": "Partly Cloudy",
            "humidity": "70%"
        }

    async def tool_create_service_request(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        ticket_id = f"SR-{uuid.uuid4().hex[:5].upper()}"
        return {
            "ticket_id": ticket_id,
            "room_number": args.get("room_number", "Unspecified"),
            "request_description": args.get("request_description"),
            "status": "DISPATCHED"
        }

    async def tool_create_support_ticket(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        ticket_id = f"TKT-{uuid.uuid4().hex[:5].upper()}"
        return {
            "ticket_id": ticket_id,
            "issue_summary": args.get("issue_summary"),
            "status": "OPEN"
        }

    async def tool_handoff_to_human(self, args: Dict[str, Any], organization_id: str, property_id: str) -> Dict[str, Any]:
        return {
            "status": "HUMAN_HANDOFF_INITIATED",
            "reason": args.get("reason", "Guest requested human assistance"),
            "assigned_desk": "Front Desk Concierge"
        }
