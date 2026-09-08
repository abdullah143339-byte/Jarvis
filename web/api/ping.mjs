export const config = { runtime: "nodejs" };

export default async function handler() {
  return Response.json({
    online: true,
    service: "JARVIS",
    time: new Date().toISOString(),
  });
}