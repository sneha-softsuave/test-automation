import { GenerateTestCase } from '../GenerateTestCase/GenerateTestCase';

interface Props {
  projectName: string;
}

export const ProjectGenerateTestCase = ({ projectName }: Props) => {
  return <GenerateTestCase projectName={projectName} />;
};
