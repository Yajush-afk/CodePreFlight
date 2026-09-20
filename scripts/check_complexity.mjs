import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const root = "apps/cli/src";
// Reviewed exemption: SessionView is a declarative Ink layout, not workflow logic.
const renderExemptions = new Set(["tui.tsx:SessionView"]);
const isFunction = node => ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node) || ts.isMethodDeclaration(node) || ts.isConstructorDeclaration(node) || ts.isGetAccessorDeclaration(node) || ts.isSetAccessorDeclaration(node);
const decisions = new Set([ts.SyntaxKind.IfStatement, ts.SyntaxKind.ConditionalExpression, ts.SyntaxKind.ForStatement, ts.SyntaxKind.ForInStatement, ts.SyntaxKind.ForOfStatement, ts.SyntaxKind.WhileStatement, ts.SyntaxKind.DoStatement, ts.SyntaxKind.CatchClause, ts.SyntaxKind.CaseClause]);
const booleanOperators = new Set([ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken]);
let failures = 0;
for (const filename of fs.readdirSync(root, { recursive: true }).filter(name => /\.tsx?$/.test(name) && !name.includes(".test.") && !name.includes(".generated."))) {
  const file = ts.createSourceFile(filename, fs.readFileSync(path.join(root, filename), "utf8"), ts.ScriptTarget.Latest, true);
  const visit = node => {
    if (isFunction(node) && node.body) {
      const name = node.name?.getText(file) ?? node.parent?.name?.getText(file) ?? "callback";
      const first = file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1;
      const length = file.getLineAndCharacterOfPosition(node.end).line + 2 - first;
      let complexity = 1;
      const count = child => {
        if (isFunction(child)) return;
        if (decisions.has(child.kind)) complexity++;
        if (ts.isBinaryExpression(child) && booleanOperators.has(child.operatorToken.kind)) complexity++;
        ts.forEachChild(child, count);
      };
      count(node.body);
      if (!renderExemptions.has(`${filename}:${name}`) && (complexity > 12 || length > 80)) {
        console.error(`${filename}:${first} ${name}: complexity ${complexity}/12, length ${length}/80`);
        failures++;
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
}
if (failures) process.exitCode = 1;
else console.log("TypeScript complexity gates passed (12 decisions, 80 lines).");
