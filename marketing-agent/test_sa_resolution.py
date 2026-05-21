import google.auth
from google.auth.compute_engine import Credentials as CECreds

def main():
    try:
        creds, project = google.auth.default()
        email = getattr(creds, "service_account_email", None)
        print(f"Auth Type: {type(creds)}")
        print(f"Email: {email}")
        
        # Test if it's ComputeEngineCredentials
        if isinstance(creds, CECreds):
            print("Is ComputeEngineCredentials")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
