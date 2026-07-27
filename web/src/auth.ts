import { User, UserManager, WebStorageStateStore } from "oidc-client-ts";

declare global {
  interface Window {
    AX_CONFIG?: {
      authMode?: string;
      cognitoIssuer?: string;
      cognitoClientId?: string;
      oidcIssuer?: string;
      oidcClientId?: string;
    };
  }
}

const config = window.AX_CONFIG ?? {};
const oidcEnabled = config.authMode === "cognito" || config.authMode === "keycloak";
const authority =
  config.authMode === "keycloak" ? config.oidcIssuer : config.cognitoIssuer;
const clientId =
  config.authMode === "keycloak" ? config.oidcClientId : config.cognitoClientId;

const userManager = oidcEnabled
  ? new UserManager({
      authority: authority!,
      client_id: clientId!,
      redirect_uri: `${window.location.origin}/auth/callback`,
      post_logout_redirect_uri: `${window.location.origin}/login`,
      response_type: "code",
      scope: "openid email profile",
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
      automaticSilentRenew: false,
    })
  : null;

export function isOidcEnabled() {
  return oidcEnabled;
}

export function authProviderName() {
  return config.authMode === "keycloak" ? "Keycloak" : "Cognito";
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
  const cognitoGroups = user.profile["cognito:groups"];
  const realmAccess = user.profile["realm_access"] as
    | { roles?: unknown[] }
    | undefined;
  const values = [
    ...(Array.isArray(cognitoGroups) ? cognitoGroups.map(String) : []),
    ...(Array.isArray(realmAccess?.roles) ? realmAccess.roles.map(String) : []),
  ];
  if (values.includes("system_admin")) return "system_admin";
  if (values.includes("operator_manager")) return "operator_manager";
  if (values.includes("field_worker")) return "field_worker";
  return "authenticated";
}
