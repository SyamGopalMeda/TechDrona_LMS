const web = "D:/company website/techdrona LMS/apps/web/";
export default {
  root: web,
  resolve: { alias: { "@": web + "src" } },
  test: { environment: "node", globals: true, dir: "D:/company website/techdrona LMS/apps/api/tests/_audit_scratch/security/web", include: ["**/*.audit.test.ts"] },
};
