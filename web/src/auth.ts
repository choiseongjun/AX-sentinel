import { User, UserManager, WebStorageStateStore } from "oidc-client-ts";

declare global {
  interface Window {
    AX_CONFIG?: {
      authMode?: string;
      cognitoIssuer?: string;
      cognitoClientId?: string;
    };
  }
}

const config = window.AX_CONFIG ?? {};
const cognitoEnabled = config.authMode === "cognito";

const userManager = cognitoEnabled
  ? new UserManager({
      authority: config.cognitoIssuer!,
      client_id: config.cognitoClientId!,
      redirect_uri: `${window.location.origin}/auth/callback`,
      post_logout_redirect_uri: `${window.location.origin}/login`,
      response_type: "code",
      scope: "openid email profile",
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
      automaticSilentRenew: false,
    })
  : null;

export function isCognitoEnabled() {
  return cognitoEnabled;
}

export async function beginSignIn() {
  if (userManager) await userManager.signinRedirect();
}

export async function restoreUser(): Promise<User | null> {
  if (!userManager) return null;
  if (window.location.pathname === "/auth/callback") {
    const user = await userManager.signinRedirectCallback();
    window.history.replaceState({}, "", "/");
    return user;
  }
  return userManager.getUser();
}

export async function signOut() {
  if (userManager) await userManager.signoutRedirect();
}

export async function getAccessToken() {
  const user = await userManager?.getUser();
  return user?.expired ? null : user?.access_token;
}

export function roleFromUser(user: User) {
  const groups = user.profile["cognito:groups"];
  const values = Array.isArray(groups) ? groups.map(String) : [];
  if (values.includes("system_admin")) return "system_admin";
  if (values.includes("operator_manager")) return "operator_manager";
  if (values.includes("field_worker")) return "field_worker";
  return "authenticated";
}
