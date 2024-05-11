const assert = require('assert');

describe('Markdown It Front Matter', () => {

  let foundFrontmatter = undefined;
  const md = require('markdown-it')()
    .use(require('../index'), fm => { foundFrontmatter = fm; });

  beforeEach(() => {
    foundFrontmatter = undefined;
  });

  it('should parse empty front matter', () => {
    assert.equal(
      md.render([
        '---',
        '---',
        '# Head'
      ].join('\n')),
      '\n<h1>Head</h1>\n');

    assert.equal(foundFrontmatter, '');
  });

  it('should parse basic front matter', () => {
    assert.equal(
      md.render([
        '---',
        'x: 1',
        '---',
        '# Head'
      ].join('\n')),
      '\n<h1>Head</h1>\n');

    assert.equal(foundFrontmatter, 'x: 1');
  });

  it('should parse until triple dots', () => {
    assert.equal(
      md.render([
        '---',
        'x: 1',
        '...',
        '# Head'
      ].join('\n')),
      '\n<h1>Head</h1>\n');

    assert.equal(foundFrontmatter, 'x: 1');
  });

  it('should parse front matter with indentation', () => {
    const frontmatter = [
      'title: Associative arrays',
      'people:',
      '    name: John Smith',
      '    age: 33',
      'morePeople: { name: Grace Jones, age: 21 }',
    ].join('\n');

    assert.equal(
      md.render([
        '---',
        frontmatter,
        '---',
        '# Head'
      ].join('\n')),
      '\n<h1>Head</h1>\n');

    assert.equal(foundFrontmatter, frontmatter);
  });

  it('should ignore spaces after front matter delimiters', () => {
    assert.equal(
      md.render([
        '---   ',
        'x: 1',
        '---  ',
        '# Head'
      ].join('\n')),
      '\n<h1>Head</h1>\n');

    assert.equal(foundFrontmatter, '  \nx: 1');
  });

  it('should ignore front matter with less than 3 opening dashes', () => {
    assert.equal(
      md.render([
        '--',
        'x: 1',
        '---',
        '# Head'
      ].join('\n')),
      '<h2>--\nx: 1</h2>\n<h1>Head</h1>\n');

    assert.equal(foundFrontmatter, undefined);
  });

  it('should require front matter have matching number of opening and closing dashes', () => {
    assert.equal(
      md.render([
        '----',
        'x: 1',
        '---',
        '# Head'
      ].join('\n')),
      '');

    assert.equal(foundFrontmatter, 'x: 1\n---');
  });

  it('Should set correct map for front-matter token', () => {
    {
      const tokens = md.parse([
        '----',
        'x: 1',
        '---',
        '# Head'
      ].join('\n'));

      assert.strictEqual(tokens[0].type, 'front_matter');
      assert.deepStrictEqual(tokens[0].map, [0, 4]);
    }
    {
      const tokens = md.parse([
        '----',
        'title: Associative arrays',
        'people:',
        '    name: John Smith',
        '    age: 33',
        'morePeople: { name: Grace Jones, age: 21 }',
        '---',
        '# Head'
      ].join('\n'));

      assert.strictEqual(tokens[0].type, 'front_matter');
      assert.deepStrictEqual(tokens[0].map, [0, 8]);
    }
  });
});
