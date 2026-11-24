/**
 * ESLint rule: ban comments except `// Critical: <why>` blocks.
 *
 * A Critical comment may continue on directly following `//` lines. Everything
 * else is reported, including directive comments, so pair it with
 * `linterOptions: { noInlineConfig: true }` to make eslint-disable inert.
 *
 * Usage (flat config):
 *   import noComments from "./tools/eslint/no-comments.js";
 *   export default [{
 *     files: ["src/**\/*.{js,jsx,ts,tsx}"],
 *     linterOptions: { noInlineConfig: true, reportUnusedDisableDirectives: "error" },
 *     plugins: { local: { rules: { "no-comments": noComments } } },
 *     rules: { "local/no-comments": "error" },
 *   }];
 *
 * Options: [{ allow: "<regex source>" }] overrides the Critical pattern;
 * [{ allowJsdocTypes: true }] keeps JSDoc blocks that contain only @type,
 * @param {T}, @returns {T}, @template, @typedef tags (for JS-with-JSDoc repos).
 */

const DEFAULT_ALLOW = "^\\s*Critical:\\s*\\S";
const SHAPE_ONLY = /^\*?\s*(\*\s*(@(type|param|returns?|template|typedef|property|satisfies)\s+\{[^}]*\}(\s+\[?[\w.$]+\]?)?)?\s*)*$/;

export default {
  meta: {
    type: "suggestion",
    schema: [
      {
        type: "object",
        properties: { allow: { type: "string" }, allowJsdocTypes: { type: "boolean" } },
        additionalProperties: false,
      },
    ],
    messages: {
      banned:
        "Comments are banned. Make the code say it: rename, extract a well-named function, or add a type. " +
        "Durable facts go in CLAUDE.md under 'Facts code can't show'. The only exception is `// Critical: <why>` " +
        "for an invariant the code cannot express whose violation causes a bug, security hole, or data loss.",
    },
  },
  create(context) {
    const options = context.options[0] ?? {};
    const allow = new RegExp(options.allow ?? DEFAULT_ALLOW);
    const sourceCode = context.sourceCode ?? context.getSourceCode();
    return {
      Program() {
        let exemptUntilLine = -1;
        for (const comment of sourceCode.getAllComments()) {
          if (comment.type === "Shebang") continue;
          const isLine = comment.type === "Line";
          const ownLine = sourceCode.lines[comment.loc.start.line - 1].trim().startsWith("//");
          if (isLine && ownLine && comment.loc.start.line === exemptUntilLine + 1) {
            exemptUntilLine = comment.loc.end.line;
            continue;
          }
          if (isLine && ownLine && allow.test(comment.value)) {
            exemptUntilLine = comment.loc.end.line;
            continue;
          }
          exemptUntilLine = -1;
          if (options.allowJsdocTypes && comment.type === "Block" && comment.value.startsWith("*") && SHAPE_ONLY.test(comment.value.replace(/\n/g, " "))) {
            continue;
          }
          context.report({ loc: comment.loc, messageId: "banned" });
        }
      },
    };
  },
};
