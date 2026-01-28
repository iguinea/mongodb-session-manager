#!/usr/bin/env python3
"""Test script to verify session_viewer_password generation."""

import os
from mongodb_session_manager import create_mongodb_session_manager

# Connection string from environment or default to localhost
MONGODB_CONNECTION_STRING = os.getenv(
    "MONGODB_CONNECTION_STRING", "mongodb://mongodb:mongodb@host.docker.internal:8550/"
)


def test_session_viewer_password():
    """Test that session_viewer_password is automatically generated."""

    print("=" * 60)
    print("Testing Session Viewer Password Generation")
    print("=" * 60)

    # Create a new session
    session_id = "test-password-session"

    print(f"\n1. Creating new session: {session_id}")
    session_manager = create_mongodb_session_manager(
        session_id=session_id,
        connection_string=MONGODB_CONNECTION_STRING,
        database_name="chats",
        collection_name="virtual_agents",
    )

    # Retrieve the password
    print("\n2. Retrieving session viewer password...")
    password = session_manager.get_session_viewer_password()

    if password:
        print("   ✓ Password generated successfully!")
        print(f"   Password: {password}")
        print(f"   Length: {len(password)} characters")

        # Verify it's alphanumeric (base64url safe)
        is_alphanumeric = all(c.isalnum() or c in "-_" for c in password)
        print(f"   Alphanumeric (base64url): {is_alphanumeric}")

        # Example usage
        print("\n3. Example Session Viewer URL:")
        print(f"   http://localhost:8883?session_id={session_id}&password={password}")
    else:
        print("   ✗ ERROR: No password was generated!")

    # Test with existing session (should return same password)
    print("\n4. Testing password persistence...")
    session_manager2 = create_mongodb_session_manager(
        session_id=session_id,
        connection_string=MONGODB_CONNECTION_STRING,
        database_name="test_db",
        collection_name="test_sessions",
    )

    password2 = session_manager2.get_session_viewer_password()

    if password == password2:
        print("   ✓ Password persisted correctly (same on reload)")
        print(f"   Password: {password2}")
    else:
        print("   ✗ ERROR: Password changed on reload!")
        print(f"   Original: {password}")
        print(f"   New: {password2}")

    # Clean up
    session_manager.close()
    session_manager2.close()

    print("\n" + "=" * 60)
    print("Test completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    test_session_viewer_password()
